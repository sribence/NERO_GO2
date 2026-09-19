"""Mock-only LowCmd construction/send path for manual joint-level control.

Status (2026-09-17): this module exists to prove that a safety-clamped
LowCmd command dict can be built correctly. It NEVER talks to a real robot.
There is no code path here that imports unitree_sdk2py's DDS channel or
opens a network interface. app.py does not import or wire this module into
its startup — it is exercised only by tests/test_lowcmd_sender.py tonight.

Every LowCmd(target_q, current_q, ...) call is routed through the caller-
supplied JointSafetyManager.clamp_full() FIRST. LowCmdSender never sends
raw/unclamped joint values; the constructed command dict is built directly
from clamp_full()'s return value.

Real Unitree LowCmd_ field names verified from source tonight
(https://github.com/unitreerobotics/unitree_sdk2_python, master,
example/go2/low_level/go2_stand_example.py + unitree_legged_const.py):

    low_cmd = unitree_go_msg_dds__LowCmd_()   # from unitree_sdk2py.idl.default
    low_cmd.head[0] = 0xFE
    low_cmd.head[1] = 0xEF
    low_cmd.level_flag = 0xFF          # LOWLEVEL, from unitree_legged_const.py
    low_cmd.gpio = 0
    low_cmd.motor_cmd[i].mode = 0x01   # PMSM mode, i in range(20) (only 0-11 used for Go2 legs)
    low_cmd.motor_cmd[i].q   = <float>
    low_cmd.motor_cmd[i].dq  = <float>  # velocity feedforward; go2.VelStopF (16000.0) is the SDK's "no velocity target" sentinel
    low_cmd.motor_cmd[i].kp  = <float>
    low_cmd.motor_cmd[i].kd  = <float>
    low_cmd.motor_cmd[i].tau = <float>
    low_cmd.crc = CRC().Crc(low_cmd)   # computed immediately before publish, from unitree_sdk2py.utils.crc
    publisher = ChannelPublisher("rt/lowcmd", LowCmd_); publisher.Write(low_cmd)

Control-loop rate verified from the same example: `RecurrentThread(interval=0.002, ...)`
i.e. 500 Hz / 2 ms per LowCmd publish. That is the basis for _MIN_TICK_INTERVAL_S below.

Still UNVERIFIED / not used here: the exact `PosStopF` (2.146e9) /
`VelStopF` (16000.0) "hold current position" sentinel semantics, and
whether `dq` should be 0.0 or VelStopF for a pure position+feedforward-
torque manual command — the example only ever sets dq=0 during its own
scripted stand-up, so that convention (dq=0.0, not VelStopF) is what this
module mirrors, but it has not been confirmed against Unitree's own
low-level control documentation. Flagged here rather than silently guessed.

The real publish side (ChannelPublisher/ChannelFactoryInitialize/CRC) is
NOT implemented in this module at all — building it is explicitly out of
scope for tonight (see docs/17-joint-szintu-kezi-vezerles-biztonsag.md).
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger("nero_go2.web_dashboard.lowcmd_sender")

# 500 Hz / 2 ms, matching unitree_sdk2py's own go2_stand_example.py
# RecurrentThread(interval=0.002, ...) LowCmd publish loop. This is a
# *log-and-warn* guard for the mock sender, not an enforced rate limiter —
# tonight's goal is proving the command math, not building the real
# control-loop timing.
_MIN_TICK_INTERVAL_S = 0.002

# Head bytes / level flag from unitree_legged_const.py + go2_stand_example.py.
_LOWCMD_HEAD = (0xFE, 0xEF)
_LOWLEVEL_FLAG = 0xFF
_PMSM_MODE = 0x01


class LowCmdSender:
    """Builds safety-clamped LowCmd-shaped command dicts and records them.

    This class has exactly one way to produce a command: everything passed
    through send() is first run through the JointSafetyManager it was
    constructed with. There is no bypass method that skips clamp_full().

    send() only appends the constructed command to self.sent — it never
    imports unitree_sdk2py, never opens a DDS channel, and never touches a
    network interface. Mirroring app.py's own MOCK_SDK=1 pattern, a "real"
    publish path is simply not implemented here rather than merely disabled,
    so there is nothing gated behind an env var that could be flipped on by
    mistake.
    """

    def __init__(self, safety, tick_interval_s=_MIN_TICK_INTERVAL_S):
        self.safety = safety
        self.tick_interval_s = tick_interval_s
        self.sent = []  # list of constructed command dicts, oldest first
        self._last_send_monotonic = None

    def build_command(self, target_q, current_q, kp=20.0, kd=1.0, tau=None):
        """Runs the requested command through JointSafetyManager.clamp_full()
        and shapes the result into a LowCmd-ready dict. Does not send/record
        anything — send() calls this internally; exposed separately so tests
        can inspect the clamp step without needing the rate-guard side effect.
        """
        safe = self.safety.clamp_full(target_q, current_q, kp=kp, kd=kd, tau=tau)
        motor_cmd = [
            {
                "mode": _PMSM_MODE,
                "q": safe["q"][i],
                "dq": 0.0,
                "kp": safe["kp"][i],
                "kd": safe["kd"][i],
                "tau": safe["tau"][i],
            }
            for i in range(12)
        ]
        return {
            "head": _LOWCMD_HEAD,
            "level_flag": _LOWLEVEL_FLAG,
            "gpio": 0,
            "motor_cmd": motor_cmd,
            # Real LowCmd_ requires a CRC computed via unitree_sdk2py's own
            # CRC().Crc(low_cmd) immediately before publish. This mock
            # command dict is never published, so no CRC is computed —
            # left explicitly absent (not faked as 0 or None-with-meaning)
            # so nothing downstream mistakes this for a wire-ready message.
        }

    def send(self, target_q, current_q, kp=20.0, kd=1.0, tau=None):
        """Mock send: builds the safety-clamped command and appends it to
        self.sent. Never calls any DDS/network API — there is no such call
        anywhere in this class for a real path to accidentally take.
        Returns the constructed command dict."""
        now = time.monotonic()
        if self._last_send_monotonic is not None:
            elapsed = now - self._last_send_monotonic
            if elapsed < self.tick_interval_s:
                logger.warning(
                    "lowcmd_sender: send() called %.4fs after the previous "
                    "call, faster than the %.4fs (500Hz) reference tick "
                    "from unitree_sdk2py's own LowCmd publish loop",
                    elapsed, self.tick_interval_s,
                )
        self._last_send_monotonic = now

        command = self.build_command(target_q, current_q, kp=kp, kd=kd, tau=tau)
        self.sent.append(command)
        logger.info("lowcmd_sender: MOCK send recorded (no DDS, no network, no robot)")
        return command
