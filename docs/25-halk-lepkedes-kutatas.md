# Halk lépkedés (ADV-7) — kutatás és terv

Döntés (2026-10-02): az új fejlesztések **ROS 2 alapon**, lokális gépen + **Isaac Sim / Isaac Lab** szimulációban készülnek és tanulnak, valódi robotra csak utána.

## 1. Mit mond az irodalom
| Forrás | Módszer | Eredmény |
|---|---|---|
| [Learning Quiet Walking for a Small Home Robot (arXiv 2502.10983, ETH)](https://arxiv.org/abs/2502.10983) | RL; **a talp érintkezési sebességének büntetése** (a lépészaj fő oka) + **tanult, változó PD-erősítés** (ízületenként aktív csillapítás / merevítés) + talp-kontakt érzékelés + curriculum (a büntetés fokozatosan nő). Két fázis: előbb járni tanul, utána halkítja (×5 súly a kontakt-sebesség büntetésre). | −4.88 dB átlagos hangnyomás |
| [QuietWalk (arXiv 2604.23702)](https://arxiv.org/abs/2604.23702) | RL; propriocepcióból (PINN, inverz dinamika) becsült lábankénti függőleges talajreakció-erő → az ütközési erő csúcsa büntetve | −7.17 dB átlag, −4.98 dB csúcs (humanoid) |

**Következtetés:** halk járás = puha talpra érkezés. Ehhez a policy-nek kell megtanulnia lassan leengedni a lábat és rugalmasan fogadni az érkezést. A gyári high-level `Move` / `SportClient` erre **nem** képes, ehhez saját RL-policy kell **low-level** (`LowCmd`) vezérléssel.

## 2. Megoldási szintek
| Szint | Mit | Hatás | Kockázat |
|---|---|---|---|
| S0 — azonnal, gyári API | lassú sebesség (`stealth` ≤ 0.25 m/s), `ClassicWalk` / `StaticWalk` (ha a firmware tudja, `/capabilities`), alacsony testmagasság, kis lépésmagasság (ha az SDK ad rá paramétert) | kicsi–közepes | nincs |
| S1 — talaj-tudatosság | a voxeltérkép + LiDAR-intenzitás + RGB → talaj-osztály (csempe / fém / fa / szőnyeg / fű); kemény talajon a `stealth` profil szigorúbb, és a tervező a puha felületet preferálja (költségréteg) | közepes | nincs |
| S2 — saját RL „stealth” policy (Isaac Lab) | low-level policy a fenti jutalom-tagokkal | **nagy** (irodalom: −5..−7 dB) | magas: a `LowCmd`-hez le kell kapcsolni a gyári sport módot → safety-réteg kell (doc 17) |
| S3 — hardver | gumi / habos talpbetét (lábvég-burkolat) | közepes, olcsó | a csúszás és a kopás változik — szimulációban a súrlódást randomizálni kell |

## 3. S2 terv — RL pipeline (Isaac Lab → ROS 2 → Go2)
1. **Alap:** Isaac Lab `Isaac-Velocity-Rough-Unitree-Go2-v0` (rsl_rl PPO) vagy [unitree_rl_gym](https://github.com/unitreerobotics/unitree_rl_gym) (Train → Play → Sim2Sim (MuJoCo) → Sim2Real); referencia: [go2_rl_gym](https://github.com/wty-yy/go2_rl_gym), [go2-phoenix](https://github.com/yusufdxb/go2-phoenix) (ONNX export + ROS 2 policy node + fail-closed safety).
2. **Jutalom-tagok (stealth fázis):**
   - `-w_cv · Σ v_z,foot²` a touchdown pillanatában (a kontakt-sebesség, a fő tag)
   - `-w_imp · Σ max(0, ΔF_z / Δt)` (ütközési erő meredeksége)
   - `-w_peak · Σ max(0, F_z − F_lim)`
   - `+` lábkontakt-idő / swing-magasság tag (ne csoszogjon)
   - meglévő tagok: követési hiba, energia, nyomaték, akció-simaság
   - curriculum: `w_cv` 0 → ×5 a 2. fázisban
3. **Akció-tér:** ízület-pozíció **+ ízületenkénti Kp/Kd skála** (a tanult PD-erősítés, mint az ETH-cikkben), korlátokkal.
4. **Domain randomization:** súrlódás, talajkeménység (contact stiffness / damping), tömeg (+7 USB-eszköz, konzol), motor-késleltetés, PD-szórás, talajfajták.
5. **Zajmérés szimulációban:** proxy = kontakt-sebesség és impulzus. Valódi mérés: dB(A) mérő, 1 m, csempén / fán / szőnyegen, A/B a gyári járással.
6. **Sim2Sim:** MuJoCo-ban ellenőrzés, mielőtt valódi robotra kerül.
7. **ROS 2 deploy:** policy-node (ONNX, 50 Hz) → `LowCmd` 500 Hz bridge; a `safety_guard` továbbra is a sebesség-parancs kapuja (a policy bemenete a guard által szűrt `cmd_vel`).
8. **Valódi robot (csak a doc 17 safety-réteggel):**
   - joint limit, rate limit, Kp/Kd cap, watchdog, E-stop
   - felfüggesztve (állvány / heveder) kezdeni, majd sík talajon
   - mindig vissza lehet váltani a gyári sport módra

## 4. Váltás a módok között
`stealth` misszió-profil → ha az S2 policy elérhető és validált: policy-mód; különben S0 + S1. A váltás csak álló helyzetben (stand → policy betöltés → stand).

## 6. Sport mód vs. saját low-level — hibrid működés
| | Gyári sport mód | Saját low-level (`LowCmd`) |
|---|---|---|
| Ki számolja a járást | a Unitree beépített mozgásvezérlője a roboton | a mi policy-nk (Jetson / ROS 2), 500 Hz `rt/lowcmd` |
| Mit küldünk | `SportClient`: `Move(vx,vy,vyaw)`, gaitek, akciók (ugrás, ül, hello…) | 12 motor: pozíció, sebesség, Kp, Kd, nyomaték + CRC |
| Váltás | — | `MotionSwitcherClient.ReleaseMode()` (sport ki), `CheckMode()` (mi aktív), `SelectMode(name)` (vissza) — [go2_stand_example.cpp](https://github.com/unitreerobotics/unitree_sdk2/blob/main/example/go2/go2_stand_example.cpp) |
| Ha leáll a vezérlő | a sport mód tartja magát | a robot **összeesik** (nincs, ami tartsa) → watchdog kell |

**Hibrid (javasolt):** alapból sport mód (minden gyári mód, gyors váltás). Csak a `stealth` futtatja a saját policy-t:
1. sport: `StandDown` (fekvés) → `ReleaseMode()` → `CheckMode()` = üres
2. saját policy: feláll → lopakodik → leül / lefekszik
3. `SelectMode(<sport>)` → `RecoveryStand` → minden gyári mód újra elérhető

- A váltás **nem azonnali**: a gyári példa 5 s-os ciklusokban próbálkozik. A tényleges idő mérendő; becslés: néhány s + a felállás.
- Váltani csak stabil pózban (fekve) szabad, menet közben soha.
- **Vészhelyzet lopakodás közben** (gyorsan el kell menni): vagy elfogadjuk a váltási időt, vagy a stealth policy-t **gyors menekülésre is** tanítjuk (`cmd_vel` 0–1.5 m/s tartomány, a jutalomban a zaj súlya a sebességgel csökken). Javaslat: az utóbbi, mert Isaac Labben egy policy több sebességtartományra tanítható.
- **A futást nem kell külön tanítani**, ha sport módban maradunk hozzá; csak akkor kell, ha a stealth módból váltás nélkül akarunk futni.
- Biztonság: a `ReleaseMode` után minden a mi kódunkon múlik (doc 17: limit, watchdog, E-stop). Az első tesztek felfüggesztett robottal.

## 5. TODO
- [ ] S0: `/capabilities` futtatása a valódi roboton → mely gait / testmagasság API él
- [ ] S1: talaj-osztályozó a voxeltérképre + költségréteg
- [ ] S2-a: Isaac Lab Go2 env + stealth reward + curriculum, tanítás lokális GPU-n
- [ ] S2-b: MuJoCo sim2sim, ONNX export, ROS 2 policy node
- [ ] S2-c: `LowCmd` bridge + safety-réteg (doc 17), felfüggesztett teszt
- [ ] S3: talpbetét-prototípus + súrlódás-mérés
- [ ] Mérés: `ReleaseMode` → `SelectMode` oda-vissza váltási idő, fekvő pózból
- [ ] Zajmérési protokoll (dB(A), 3 talaj, A/B)
