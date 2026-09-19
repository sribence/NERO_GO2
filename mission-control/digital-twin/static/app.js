/* mission-control :: digital-twin operator console
 *
 * Vanilla JS + three.js (CDN, no build step). Renders the dual-layer map
 * (floor + walls) from the `mapping` pillar, shows live robot state from
 * `core`, and lets an operator send the robot to a point on the floor.
 *
 * Coordinate convention (documented here once):
 *   world (x, y) maps onto the three.js scene as (sceneX, sceneZ), with
 *   sceneY as "up". Internally consistent flattening, not a calibrated
 *   compass orientation -- see README.md.
 *
 * Safety rules this file implements (AUDIT-2026-09-10.md, P0-10):
 *   - E-stop is reachable from every screen state, by tap or by keyboard
 *   - motion is never one stray tap away: goto requires confirmation
 *   - battery / armed / link latency are always on screen, never buried
 */

(() => {
  "use strict";

  // -------------------------------------------------------------------
  // i18n
  // -------------------------------------------------------------------
  const I18N = {
    hu: {
      connecting: "csatlakozás…", live: "élő", reconnecting: "újracsatlakozás…",
      offline: "nincs kapcsolat", batt: "akku", state: "állapot",
      armed: "ÉLES", disarmed: "LEZÁRVA", details: "részletek",
      pose: "pozíció x,y", yaw: "irány", mapsize: "térkép", coverage: "lefedettség",
      nearest: "legközelebbi tárgy", loc: "lokalizáció", lastgoto: "utolsó cél",
      gotoq: "Ide küldjem a robotot?", cancel: "Mégse", send: "Indítás",
      estophint: "(Szóköz)", cancelnav: "Megállít",
      alertEstop: "VÉSZLEÁLLÍTÁS kiadva — a robot leállt és lezárva",
      alertLink: "Megszakadt a kapcsolat a robottal",
      alertBattLow: "Alacsony akkumulátor",
      alertBattCrit: "KRITIKUS akkumulátorszint",
      alertProx: "Tárgy vagy személy túl közel",
      alertBrake: "Vészfék: akadály a haladási irányban",
      alertNavFail: "A navigáció meghiúsult",
      alertSent: "Navigációs parancs elfogadva",
      alertNoNav: "A navigációs szolgáltatás nem elérhető",
      alertDisarmed: "A robot lezárva — előbb élesíteni kell",
      notImpl: "nincs implementálva",
    },
    en: {
      connecting: "connecting…", live: "live", reconnecting: "reconnecting…",
      offline: "disconnected", batt: "batt", state: "state",
      armed: "ARMED", disarmed: "DISARMED", details: "details",
      pose: "pose x,y", yaw: "yaw", mapsize: "map", coverage: "coverage",
      nearest: "nearest object", loc: "localization", lastgoto: "last goal",
      gotoq: "Send the robot here?", cancel: "Cancel", send: "Go",
      estophint: "(Space)", cancelnav: "Stop",
      alertEstop: "EMERGENCY STOP issued — robot stopped and disarmed",
      alertLink: "Lost connection to the robot",
      alertBattLow: "Battery low",
      alertBattCrit: "CRITICAL battery level",
      alertProx: "Object or person too close",
      alertBrake: "Safety brake: obstacle ahead",
      alertNavFail: "Navigation failed",
      alertSent: "Navigation command accepted",
      alertNoNav: "Navigation service unavailable",
      alertDisarmed: "Robot is disarmed — arm it first",
      notImpl: "not implemented",
    },
  };
  let lang = localStorage.getItem("mc_lang") || "hu";
  const t = (k) => (I18N[lang] && I18N[lang][k]) || k;

  const $ = (id) => document.getElementById(id);
  const els = {
    connDot: $("conn-dot"), connText: $("conn-text"), connChip: $("conn-chip"), latency: $("latency"),
    battChip: $("batt-chip"), battFill: $("batt-fill"), battPct: $("batt-pct"),
    armedChip: $("armed-chip"), armedText: $("armed-text"),
    navState: $("nav-state"), demoChip: $("demo-chip"), langBtn: $("lang-btn"),
    alerts: $("alerts"), details: $("details"), caret: $("details-caret"),
    poseXY: $("pose-xy"), poseYaw: $("pose-yaw"), poseLevel: $("pose-level"),
    mapSize: $("map-size"), mapCoverage: $("map-coverage"),
    proximity: $("proximity"), confPct: $("conf-pct"), lastGoto: $("last-goto"),
    gotoConfirm: $("goto-confirm"), gotoMeta: $("goto-meta"),
    gotoYes: $("goto-yes"), gotoNo: $("goto-no"),
    estop: $("estop"), cancelNav: $("cancel-nav"),
  };

  function applyLang() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach((el) => {
      el.textContent = t(el.dataset.i18n);
    });
    els.langBtn.textContent = lang === "hu" ? "EN" : "HU";
  }
  els.langBtn.addEventListener("click", () => {
    lang = lang === "hu" ? "en" : "hu";
    localStorage.setItem("mc_lang", lang);
    applyLang();
  });

  // -------------------------------------------------------------------
  // Alert stack -- three severities, deduplicated by key
  // -------------------------------------------------------------------
  const activeAlerts = new Map();

  function alert(key, severity, textKey, extra) {
    if (activeAlerts.has(key)) {
      const node = activeAlerts.get(key);
      if (node.dataset.sev === severity) return;
      node.remove();
      activeAlerts.delete(key);
    }
    const node = document.createElement("div");
    node.className = `alert ${severity}`;
    node.dataset.sev = severity;
    const mark = severity === "crit" ? "●" : severity === "warn" ? "▲" : "ℹ";
    node.innerHTML = `<span class="sev"></span><span class="msg"></span>`;
    node.querySelector(".sev").textContent = mark;
    node.querySelector(".msg").textContent = t(textKey) + (extra ? ` — ${extra}` : "");
    els.alerts.appendChild(node);
    activeAlerts.set(key, node);
    if (severity === "info") setTimeout(() => clearAlert(key), 4000);
  }
  function clearAlert(key) {
    const node = activeAlerts.get(key);
    if (node) { node.remove(); activeAlerts.delete(key); }
  }

  // -------------------------------------------------------------------
  // three.js scene
  // -------------------------------------------------------------------
  const viewport = $("viewport");
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0e13);
  const camera = new THREE.PerspectiveCamera(55, window.innerWidth / window.innerHeight, 0.05, 2000);
  const renderer = new THREE.WebGLRenderer({ antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setSize(window.innerWidth, window.innerHeight);
  viewport.appendChild(renderer.domElement);

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const sun = new THREE.DirectionalLight(0xffffff, 0.8);
  sun.position.set(10, 20, 10);
  scene.add(sun);

  const orbitTarget = new THREE.Vector3(0, 0, 0);
  // Near-top-down by default: at a shallower angle the wall instances
  // occlude most of the floor, which is the layer the operator acts on.
  let camDistance = 12, camAzimuth = Math.PI * 0.25, camPolar = Math.PI * 0.17;
  let orbitInitialised = false;

  function updateCamera() {
    camera.position.set(
      orbitTarget.x + camDistance * Math.sin(camPolar) * Math.sin(camAzimuth),
      orbitTarget.y + camDistance * Math.cos(camPolar),
      orbitTarget.z + camDistance * Math.sin(camPolar) * Math.cos(camAzimuth)
    );
    camera.lookAt(orbitTarget);
  }
  updateCamera();

  window.addEventListener("resize", () => {
    camera.aspect = window.innerWidth / window.innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(window.innerWidth, window.innerHeight);
  });

  // -------------------------------------------------------------------
  // Orbit / pinch-zoom / tap, touch-aware
  // -------------------------------------------------------------------
  const pointers = new Map();
  let dragMoved = 0, pinchDist = 0;

  renderer.domElement.addEventListener("pointerdown", (ev) => {
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pointers.size === 1) dragMoved = 0;
    if (pointers.size === 2) pinchDist = pinchDistance();
  });
  function pinchDistance() {
    const [a, b] = [...pointers.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  }
  window.addEventListener("pointermove", (ev) => {
    const prev = pointers.get(ev.pointerId);
    if (!prev) return;
    const dx = ev.clientX - prev.x, dy = ev.clientY - prev.y;
    pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
    if (pointers.size === 2) {
      const d = pinchDistance();
      if (pinchDist > 0) {
        camDistance = Math.min(Math.max(camDistance * (pinchDist / d), 1.5), 400);
        updateCamera();
      }
      pinchDist = d;
      dragMoved += 99;
      return;
    }
    dragMoved += Math.abs(dx) + Math.abs(dy);
    camAzimuth -= dx * 0.005;
    camPolar = Math.min(Math.max(camPolar - dy * 0.005, 0.05), Math.PI / 2 - 0.02);
    updateCamera();
  });
  window.addEventListener("pointerup", (ev) => {
    const had = pointers.has(ev.pointerId);
    pointers.delete(ev.pointerId);
    if (!had || pointers.size > 0) return;
    if (dragMoved < 8) proposeGoto(ev.clientX, ev.clientY);
  });
  window.addEventListener("pointercancel", (ev) => pointers.delete(ev.pointerId));
  renderer.domElement.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    camDistance = Math.min(Math.max(camDistance * (ev.deltaY > 0 ? 1.1 : 0.9), 1.5), 400);
    updateCamera();
  }, { passive: false });

  // -------------------------------------------------------------------
  // Map rendering
  // -------------------------------------------------------------------
  let floorMesh = null, wallsMesh = null;

  function colorForFloorValue(v) {
    if (v < 0) return [40, 46, 56];      // unknown
    if (v >= 50) return [200, 70, 70];   // occupied
    return [24, 68, 62];                 // free
  }

  function buildFloorTexture(map) {
    const { width, height, floor } = map;
    const canvas = document.createElement("canvas");
    canvas.width = width; canvas.height = height;
    const ctx = canvas.getContext("2d");
    const img = ctx.createImageData(width, height);
    for (let i = 0; i < width * height; i++) {
      const [r, g, b] = colorForFloorValue(floor[i]);
      const p = i * 4;
      img.data[p] = r; img.data[p + 1] = g; img.data[p + 2] = b; img.data[p + 3] = 255;
    }
    ctx.putImageData(img, 0, 0);
    const tex = new THREE.CanvasTexture(canvas);
    tex.magFilter = THREE.NearestFilter;
    tex.minFilter = THREE.NearestFilter;
    return tex;
  }

  function rebuildMap(map) {
    const worldW = map.width * map.resolution;
    const worldH = map.height * map.resolution;
    const centerX = map.origin_x + worldW / 2;
    const centerZ = map.origin_y + worldH / 2;

    if (floorMesh) {
      scene.remove(floorMesh);
      floorMesh.geometry.dispose();
      if (floorMesh.material.map) floorMesh.material.map.dispose();
      floorMesh.material.dispose();
    }
    floorMesh = new THREE.Mesh(
      new THREE.PlaneGeometry(worldW, worldH),
      new THREE.MeshStandardMaterial({ map: buildFloorTexture(map), side: THREE.DoubleSide })
    );
    floorMesh.rotation.x = -Math.PI / 2;
    floorMesh.position.set(centerX, 0, centerZ);
    scene.add(floorMesh);

    if (wallsMesh) {
      scene.remove(wallsMesh);
      wallsMesh.geometry.dispose();
      wallsMesh.material.dispose();
      wallsMesh = null;
    }
    const cells = [];
    for (let i = 0; i < map.walls.length; i++) if (map.walls[i] > 0) cells.push(i);
    const render = cells.slice(0, 60000);
    if (render.length) {
      const res = map.resolution;
      wallsMesh = new THREE.InstancedMesh(
        new THREE.BoxGeometry(res * 0.95, 1, res * 0.95),
        new THREE.MeshStandardMaterial({ color: 0x6f8fae }),
        render.length
      );
      const dummy = new THREE.Object3D();
      for (let k = 0; k < render.length; k++) {
        const idx = render[k];
        const h = Math.max((map.walls[idx] / 255) * 2.2, 0.05);
        dummy.position.set(
          map.origin_x + ((idx % map.width) + 0.5) * res,
          h / 2,
          map.origin_y + (Math.floor(idx / map.width) + 0.5) * res
        );
        dummy.scale.set(1, h, 1);
        dummy.updateMatrix();
        wallsMesh.setMatrixAt(k, dummy.matrix);
      }
      wallsMesh.instanceMatrix.needsUpdate = true;
      scene.add(wallsMesh);
    }

    if (!orbitInitialised) {
      orbitInitialised = true;
      orbitTarget.set(centerX, 0, centerZ);
      // Fit by aspect too, otherwise a phone's narrow viewport starts
      // zoomed into a corner of the map.
      const fit = Math.max(worldH, worldW / Math.max(camera.aspect, 0.2));
      camDistance = Math.min(fit * 0.85 + 2, 400);
      updateCamera();
    }

    let known = 0;
    for (let i = 0; i < map.floor.length; i++) if (map.floor[i] >= 0) known++;
    els.mapSize.textContent = `${map.width}×${map.height} @ ${map.resolution}m`;
    els.mapCoverage.textContent = `${((known / map.floor.length) * 100).toFixed(1)}%`;
  }

  async function fetchMap() {
    try {
      const r = await fetch("/api/map_proxy");
      if (!r.ok) { alert("map", "warn", "alertNoNav"); return; }
      clearAlert("map");
      rebuildMap(await r.json());
    } catch (e) { alert("map", "warn", "alertNoNav"); }
  }

  // -------------------------------------------------------------------
  // Robot marker
  // -------------------------------------------------------------------
  const robotGroup = new THREE.Group();
  robotGroup.add(
    new THREE.Mesh(new THREE.SphereGeometry(0.22, 16, 12),
      new THREE.MeshStandardMaterial({ color: 0x33e0ff, emissive: 0x0d5a68 }))
  );
  const arrow = new THREE.Mesh(new THREE.ConeGeometry(0.17, 0.55, 12),
    new THREE.MeshStandardMaterial({ color: 0x33e0ff, emissive: 0x0d5a68 }));
  arrow.rotation.x = Math.PI / 2;
  arrow.position.set(0, 0, 0.42);
  robotGroup.add(arrow);
  // A beacon so the robot stays findable when walls are between it and
  // the camera -- depthTest off keeps it drawn on top.
  const beacon = new THREE.Mesh(
    new THREE.CylinderGeometry(0.035, 0.035, 3.2, 6),
    new THREE.MeshBasicMaterial({ color: 0x33e0ff, transparent: true, opacity: 0.5, depthTest: false })
  );
  beacon.position.y = 1.6;
  beacon.renderOrder = 999;
  robotGroup.add(beacon);
  robotGroup.visible = false;
  scene.add(robotGroup);

  const gotoMarker = new THREE.Mesh(
    new THREE.RingGeometry(0.18, 0.26, 24),
    new THREE.MeshBasicMaterial({ color: 0xffb84d, side: THREE.DoubleSide })
  );
  gotoMarker.rotation.x = -Math.PI / 2;
  gotoMarker.visible = false;
  scene.add(gotoMarker);

  // -------------------------------------------------------------------
  // Two-step goto
  // -------------------------------------------------------------------
  const raycaster = new THREE.Raycaster();
  const ndc = new THREE.Vector2();
  let pendingGoto = null;
  let lastPose = null;

  function proposeGoto(clientX, clientY) {
    if (!floorMesh) return;
    const rect = renderer.domElement.getBoundingClientRect();
    ndc.x = ((clientX - rect.left) / rect.width) * 2 - 1;
    ndc.y = -((clientY - rect.top) / rect.height) * 2 + 1;
    raycaster.setFromCamera(ndc, camera);
    const hits = raycaster.intersectObject(floorMesh, false);
    if (!hits.length) return;

    const p = hits[0].point;
    pendingGoto = { x: p.x, y: p.z };
    gotoMarker.position.set(p.x, 0.03, p.z);
    gotoMarker.visible = true;

    const dist = lastPose ? Math.hypot(p.x - lastPose.x, p.z - lastPose.y) : null;
    els.gotoMeta.textContent =
      `x ${p.x.toFixed(2)}   y ${p.z.toFixed(2)}` + (dist !== null ? `   ·   ${dist.toFixed(2)} m` : "");
    els.gotoConfirm.hidden = false;
  }

  els.gotoNo.addEventListener("click", () => {
    els.gotoConfirm.hidden = true;
    gotoMarker.visible = false;
    pendingGoto = null;
  });

  els.gotoYes.addEventListener("click", async () => {
    if (!pendingGoto) return;
    const target = pendingGoto;
    els.gotoConfirm.hidden = true;
    pendingGoto = null;
    els.lastGoto.textContent = `${target.x.toFixed(2)}, ${target.y.toFixed(2)}`;
    try {
      const r = await fetch("/api/goto", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(target),
      });
      if (r.status === 409) alert("goto", "warn", "alertDisarmed");
      else if (!r.ok) alert("goto", "warn", "alertNoNav");
      else alert("goto", "info", "alertSent");
    } catch (e) {
      alert("goto", "warn", "alertNoNav");
    }
  });

  // -------------------------------------------------------------------
  // E-stop and cancel
  // -------------------------------------------------------------------
  async function estop() {
    els.estop.classList.add("firing");
    try {
      await fetch("/api/estop", { method: "POST" });
      alert("estop", "crit", "alertEstop");
      setTimeout(() => clearAlert("estop"), 6000);
    } finally {
      setTimeout(() => els.estop.classList.remove("firing"), 250);
    }
  }
  els.estop.addEventListener("click", estop);
  window.addEventListener("keydown", (ev) => {
    if (ev.code === "Space" || ev.key === "Escape") { ev.preventDefault(); estop(); }
  });
  els.cancelNav.addEventListener("click", async () => {
    try { await fetch("/api/goto/cancel", { method: "POST" }); } catch (e) { /* best effort */ }
  });

  els.details.querySelector("h2").addEventListener("click", () => {
    els.details.classList.toggle("collapsed");
    els.caret.textContent = els.details.classList.contains("collapsed") ? "▸" : "▾";
  });

  // -------------------------------------------------------------------
  // Status rendering
  // -------------------------------------------------------------------
  function renderState(s) {
    if (!s) return;

    if (s.demo) els.demoChip.hidden = false;

    const pose = s.pose;
    lastPose = pose || null;
    if (pose) {
      robotGroup.visible = true;
      robotGroup.position.set(pose.x, 0.05, pose.y);
      robotGroup.rotation.y = -pose.yaw;
      els.poseXY.textContent = `${pose.x.toFixed(2)}, ${pose.y.toFixed(2)}`;
      els.poseYaw.textContent = `${((pose.yaw * 180) / Math.PI).toFixed(1)}°`;
      els.poseLevel.textContent = pose.level_id || "--";
    } else {
      robotGroup.visible = false;
    }

    const pct = s.battery ? s.battery.percent : null;
    if (pct === null || pct === undefined) {
      els.battPct.textContent = "--";
      els.battFill.style.width = "0%";
    } else {
      els.battPct.textContent = `${pct.toFixed(0)}%`;
      els.battFill.style.width = `${Math.max(0, Math.min(100, pct))}%`;
      const crit = pct <= 10, low = pct <= 20;
      els.battFill.style.background = crit ? "var(--crit)" : low ? "var(--warn)" : "var(--ok)";
      els.battChip.className = "chip" + (crit ? " bad" : low ? " warn" : "");
      if (crit) alert("batt", "crit", "alertBattCrit", `${pct.toFixed(0)}%`);
      else if (low) alert("batt", "warn", "alertBattLow", `${pct.toFixed(0)}%`);
      else clearAlert("batt");
    }

    els.armedText.textContent = s.armed ? t("armed") : t("disarmed");
    els.armedChip.className = "chip " + (s.armed ? "bad" : "good");

    const st = s.nav_state || "idle";
    els.navState.textContent = st;
    els.cancelNav.disabled = !(st === "moving" || st === "planning" || st === "blocked");
    if (st === "blocked") alert("brake", "warn", "alertBrake");
    else clearAlert("brake");
    if (st === "failed") alert("nav", "warn", "alertNavFail", s.nav_error || "");
    else clearAlert("nav");

    const prox = s.proximity;
    if (prox && prox.min_distance_m !== null && prox.min_distance_m !== undefined) {
      els.proximity.textContent = `${prox.min_distance_m.toFixed(2)} m`;
      if (prox.active) alert("prox", "warn", "alertProx", `${prox.min_distance_m.toFixed(2)} m`);
      else clearAlert("prox");
    } else {
      els.proximity.textContent = "--";
    }

    if (s.link && s.link.tracked && !s.link.healthy) alert("link", "crit", "alertLink");
    else clearAlert("link");

    // The ICP relocalization is not built; show it as absent, not as a
    // green 50% bar that reads like a real measurement.
    els.confPct.textContent = s.localization_confidence === null || s.localization_confidence === undefined
      ? `n/a (${t("notImpl")})`
      : `${Math.round(s.localization_confidence * 100)}%`;
  }

  function setConn(state, latencyMs) {
    els.connDot.className = "dot " + (state === "ok" ? "ok" : state === "reconnecting" ? "warn" : "bad");
    els.connText.textContent = t(state === "ok" ? "live" : state === "reconnecting" ? "reconnecting" : "offline");
    els.connChip.className = "chip" + (state === "ok" ? "" : state === "reconnecting" ? " warn" : " bad");
    els.latency.textContent = state === "ok" && latencyMs != null ? `${Math.round(latencyMs)}ms` : "";
  }

  // -------------------------------------------------------------------
  // WebSocket live feed
  // -------------------------------------------------------------------
  let lastMapVersion = null, reconnectDelay = 1000;

  function connectWs() {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${proto}//${location.host}/ws/live`);

    ws.onopen = () => { setConn("ok", null); reconnectDelay = 1000; };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      setConn("ok", msg.t ? Math.max(0, Date.now() - msg.t * 1000) : null);
      renderState(msg);
      if (msg.map_version != null && msg.map_version !== lastMapVersion) {
        lastMapVersion = msg.map_version;
        fetchMap();
      }
    };
    ws.onclose = () => {
      setConn("reconnecting", null);
      setTimeout(connectWs, reconnectDelay);
      reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
    };
    ws.onerror = () => ws.close();
  }

  applyLang();
  setConn("connecting", null);
  fetchMap();
  connectWs();

  (function animate() {
    requestAnimationFrame(animate);
    renderer.render(scene, camera);
  })();
})();
