import os
# Silence internal TensorFlow, MediaPipe C++, and Clearcut logs
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"
os.environ["GLOG_minloglevel"] = "3"
os.environ["GLOG_stderrthreshold"] = "3"
os.environ["GLOG_v"] = "0"
os.environ["GLOG_logtostderr"] = "0"

import sys
import json
import urllib.request
import ctypes
from ctypes import wintypes
import threading
import time
import winsound
import tkinter as tk
import customtkinter as ctk
import cv2
import mediapipe as mp
import numpy as np
from PIL import Image, ImageDraw
import pystray

# Enable Windows High-DPI awareness
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# Resolve application directory
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(sys.executable)
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

CONFIG_PATH = os.path.join(APP_DIR, "posture_profile.json")

FRIENDLY_APP_NAMES = {
    "code.exe": "VS Code",
    "devenv.exe": "Visual Studio",
    "pycharm64.exe": "PyCharm",
    "chrome.exe": "Chrome",
    "msedge.exe": "Edge",
    "firefox.exe": "Firefox",
    "brave.exe": "Brave",
    "slack.exe": "Slack",
    "discord.exe": "Discord",
    "teams.exe": "MS Teams",
    "ms-teams.exe": "MS Teams",
    "zoom.exe": "Zoom",
    "winword.exe": "Word",
    "excel.exe": "Excel",
    "powerpnt.exe": "PowerPoint",
    "notion.exe": "Notion",
    "obsidian.exe": "Obsidian",
    "explorer.exe": "File Explorer",
    "notepad.exe": "Notepad",
    "windowsterminal.exe": "Terminal",
}

# Authentic Windows 11 Dark Mode Theme
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


def get_active_app_name():
    """Lightweight, passive helper that reads the active foreground app name."""
    try:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return None

        h_proc = kernel32.OpenProcess(0x1000, False, pid.value)
        if not h_proc:
            return None

        try:
            exe_buf = ctypes.create_unicode_buffer(512)
            size = wintypes.DWORD(512)
            if kernel32.QueryFullProcessImageNameW(h_proc, 0, exe_buf, ctypes.byref(size)):
                exe_name = os.path.basename(exe_buf.value).lower()
            else:
                return None
        finally:
            kernel32.CloseHandle(h_proc)

        if exe_name in ("python.exe", "pythonw.exe", "postureguardian.exe"):
            return None

        return FRIENDLY_APP_NAMES.get(
            exe_name,
            exe_name.replace(".exe", "").capitalize()
        )
    except Exception:
        return None


# =====================================================================
#  WIN32 LAYERED CLICK-THROUGH OVERLAY (RESTORED EXACT SMOOTHNESS)
# =====================================================================
class ACCENT_POLICY(ctypes.Structure):
    _fields_ = [
        ("AccentState", ctypes.c_int),
        ("AccentFlags", ctypes.c_int),
        ("GradientColor", ctypes.c_uint),
        ("AnimationId", ctypes.c_int),
    ]


class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
    _fields_ = [
        ("Attribute", ctypes.c_int),
        ("Data", ctypes.POINTER(ACCENT_POLICY)),
        ("SizeOfData", ctypes.c_size_t),
    ]


class WindowsDesktopBiofeedback:
    """
    Creates a full-screen, click-through Windows overlay for screen dimming
    and DWM acrylic blur. Mouse clicks and typing pass directly through.
    """
    def __init__(self, parent=None):
        if parent:
            self.root = tk.Toplevel(parent)
        else:
            self.root = tk.Tk()
        self.root.overrideredirect(True)

        user32 = ctypes.windll.user32
        x = user32.GetSystemMetrics(76)       # SM_XVIRTUALSCREEN
        y = user32.GetSystemMetrics(77)       # SM_YVIRTUALSCREEN
        width = user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        height = user32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
        if width == 0 or height == 0:
            width = self.root.winfo_screenwidth()
            height = self.root.winfo_screenheight()
            x, y = 0, 0

        self.root.geometry(f"{width}x{height}+{x}+{y}")
        self.root.configure(bg="#0a0a0e")
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.0)

        self.banner = tk.Label(
            self.root,
            text="Posture reminder: Sit upright to restore full screen",
            font=("Segoe UI", 13),
            fg="#f0f0f0",
            bg="#18181c",
            padx=24,
            pady=10,
            relief="flat"
        )
        self.banner.pack(side="top", pady=28)

        self.root.update_idletasks()
        self.root.update()

        self.hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        self._make_click_through()

        SWP_NOSIZE = 0x0001
        SWP_NOMOVE = 0x0002
        SWP_NOACTIVATE = 0x0010
        SWP_SHOWWINDOW = 0x0040
        user32.SetWindowPos(
            self.hwnd, -1, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )

        self.current_alpha = 0.0
        self.use_acrylic_blur = False
        self._blur_active = False
        self.max_opacity = 0.72

    def _make_click_through(self):
        GWL_EXSTYLE = -20
        WS_EX_LAYERED = 0x00080000
        WS_EX_TRANSPARENT = 0x00000020
        WS_EX_TOPMOST = 0x00000008
        WS_EX_TOOLWINDOW = 0x00000080
        WS_EX_NOACTIVATE = 0x08000000

        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(self.hwnd, GWL_EXSTYLE)
        new_style = (
            style
            | WS_EX_LAYERED
            | WS_EX_TRANSPARENT
            | WS_EX_TOPMOST
            | WS_EX_TOOLWINDOW
            | WS_EX_NOACTIVATE
        )
        user32.SetWindowLongW(self.hwnd, GWL_EXSTYLE, new_style)

    def _set_dwm_acrylic_blur(self, enable: bool):
        if self._blur_active == enable:
            return
        self._blur_active = enable

        policy = ACCENT_POLICY()
        policy.AccentState = 4 if enable else 0
        policy.AccentFlags = 2
        policy.GradientColor = 0x99101015 if enable else 0x00000000

        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = 19
        data.Data = ctypes.pointer(policy)
        data.SizeOfData = ctypes.sizeof(policy)

        try:
            ctypes.windll.user32.SetWindowCompositionAttribute(self.hwnd, ctypes.byref(data))
        except Exception:
            pass

    def update_intensity(self, target_intensity: float, reason_text: str = ""):
        if self.current_alpha <= 0.001 and target_intensity <= 0.001:
            return

        if reason_text:
            self.banner.config(text=f"Posture reminder: {reason_text}. Sit upright to restore screen.")

        speed = 0.08 if target_intensity > self.current_alpha else 0.35
        self.current_alpha += (target_intensity - self.current_alpha) * speed

        if self.current_alpha < 0.01:
            self.current_alpha = 0.0
            if self._blur_active:
                self._set_dwm_acrylic_blur(False)
            self.root.attributes("-alpha", 0.0)
        else:
            if self.use_acrylic_blur:
                self._set_dwm_acrylic_blur(True)
            elif self._blur_active:
                self._set_dwm_acrylic_blur(False)
            self.root.attributes("-alpha", min(self.current_alpha * self.max_opacity, self.max_opacity))

        self.root.update_idletasks()
        self.root.update()

    def close(self):
        self._set_dwm_acrylic_blur(False)
        try:
            self.root.destroy()
        except Exception:
            pass


# =====================================================================
#  POSE TRACKER & BIOMECHANICAL ANALYZER (RESTORED WORKING MATH)
# =====================================================================
class PoseDetectorWrapper:
    def __init__(self):
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "pose"):
            self.mode = "solutions"
            mp_pose = mp.solutions.pose
            self.detector = mp_pose.Pose(
                static_image_mode=False,
                model_complexity=1,
                smooth_landmarks=True,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
        else:
            self.mode = "tasks"
            from mediapipe.tasks import python
            from mediapipe.tasks.python import vision

            model_file = "pose_landmarker.task"
            if hasattr(sys, "_MEIPASS"):
                bundled_model = os.path.join(sys._MEIPASS, model_file)
                model_path = bundled_model if os.path.exists(bundled_model) else os.path.join(APP_DIR, model_file)
            else:
                model_path = os.path.join(APP_DIR, model_file)

            if not os.path.exists(model_path):
                print("[INFO] Downloading MediaPipe 3D Pose Landmarker model...")
                url = "https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_full/float16/latest/pose_landmarker_full.task"
                urllib.request.urlretrieve(url, model_path)

            base_options = python.BaseOptions(model_asset_path=model_path)
            options = vision.PoseLandmarkerOptions(
                base_options=base_options,
                running_mode=vision.RunningMode.VIDEO,
                min_pose_detection_confidence=0.5,
                min_tracking_confidence=0.5
            )
            self.detector = vision.PoseLandmarker.create_from_options(options)
            self.last_timestamp_ms = 0

    def process(self, rgb_frame):
        if self.mode == "solutions":
            results = self.detector.process(rgb_frame)
            if results.pose_landmarks and results.pose_world_landmarks:
                return results.pose_landmarks.landmark, results.pose_world_landmarks.landmark
            return None, None
        else:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)
            now_ms = int(time.time() * 1000)
            if now_ms <= self.last_timestamp_ms:
                now_ms = self.last_timestamp_ms + 1
            self.last_timestamp_ms = now_ms

            results = self.detector.detect_for_video(mp_image, now_ms)
            if results.pose_landmarks and len(results.pose_landmarks) > 0:
                return results.pose_landmarks[0], results.pose_world_landmarks[0]
            return None, None


class BiomechanicalAnalyzer:
    def __init__(self, ema_alpha: float = 0.28):
        self.alpha = ema_alpha
        self.smooth_neck_ratio = None
        self.smooth_z_diff = None
        self.smooth_lateral_deg = None

    def compute(self, world_landmarks, image_landmarks):
        l_ear = np.array([image_landmarks[7].x, image_landmarks[7].y, image_landmarks[7].z])
        r_ear = np.array([image_landmarks[8].x, image_landmarks[8].y, image_landmarks[8].z])
        l_sh = np.array([image_landmarks[11].x, image_landmarks[11].y, image_landmarks[11].z])
        r_sh = np.array([image_landmarks[12].x, image_landmarks[12].y, image_landmarks[12].z])

        ear_mid = (l_ear + r_ear) / 2.0
        sh_mid = (l_sh + r_sh) / 2.0

        shoulder_width = float(np.linalg.norm(l_sh[:2] - r_sh[:2]))
        if shoulder_width < 1e-5:
            return None, None, None, False

        vertical_neck_dist = sh_mid[1] - ear_mid[1]
        raw_neck_ratio = float(vertical_neck_dist / shoulder_width)

        w_ear_z = (world_landmarks[7].z + world_landmarks[8].z) / 2.0
        w_sh_z = (world_landmarks[11].z + world_landmarks[12].z) / 2.0
        raw_z_diff = float(w_sh_z - w_ear_z)

        sh_dy = l_sh[1] - r_sh[1]
        sh_dx = max(abs(l_sh[0] - r_sh[0]), 1e-5)
        shoulder_roll_deg = float(np.degrees(np.arctan2(sh_dy, sh_dx)))

        ear_dy = l_ear[1] - r_ear[1]
        ear_dx = max(abs(l_ear[0] - r_ear[0]), 1e-5)
        head_roll_deg = float(np.degrees(np.arctan2(ear_dy, ear_dx)))
        # Restored exact unsigned magnitude combination so head & shoulder tilt never cancel out
        raw_lateral_deg = float(abs(shoulder_roll_deg) * 0.65 + abs(head_roll_deg) * 0.35)

        hand_near_face = False
        jaw_target = np.array([ear_mid[0], ear_mid[1] + 0.18 * shoulder_width])
        for idx in (15, 16, 19, 20):
            lm = image_landmarks[idx]
            if getattr(lm, "visibility", 1.0) > 0.35:
                if float(np.linalg.norm(np.array([lm.x, lm.y]) - jaw_target)) < (0.52 * shoulder_width):
                    hand_near_face = True
                    break

        if self.smooth_neck_ratio is None:
            self.smooth_neck_ratio = raw_neck_ratio
            self.smooth_z_diff = raw_z_diff
            self.smooth_lateral_deg = raw_lateral_deg
        else:
            a = self.alpha
            self.smooth_neck_ratio = a * raw_neck_ratio + (1.0 - a) * self.smooth_neck_ratio
            self.smooth_z_diff = a * raw_z_diff + (1.0 - a) * self.smooth_z_diff
            self.smooth_lateral_deg = a * raw_lateral_deg + (1.0 - a) * self.smooth_lateral_deg

        return self.smooth_neck_ratio, self.smooth_z_diff, self.smooth_lateral_deg, hand_near_face


def load_saved_profile():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def save_profile(data: dict):
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass


def create_tray_image(is_slouching: bool):
    """Creates a clean, understated Windows taskbar tray icon."""
    image = Image.new("RGBA", (32, 32), color=(0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    color = (209, 52, 56) if is_slouching else (87, 168, 119)
    draw.ellipse((4, 4, 28, 28), outline=color, width=3)
    draw.ellipse((12, 12, 20, 20), fill=color)
    return image


# =====================================================================
#  CAMERA & COMPUTATION WORKER THREAD (RESTORED CORE LOOP)
# =====================================================================
class VisionWorker(threading.Thread):
    def __init__(self, overlay: WindowsDesktopBiofeedback):
        super().__init__(daemon=True)
        self.overlay = overlay
        self.running = True
        self.paused = False
        self.cap = None

        self.pose_detector = None
        self.analyzer = BiomechanicalAnalyzer(ema_alpha=0.28)

        # Baseline & Calibration
        self.baseline_neck_ratio = None
        self.baseline_z_diff = None
        self.baseline_lateral_deg = 0.0

        # State machine
        self.slouch_delay_sec = 1.8
        self.hand_pause_max_sec = 3.8
        self.thresh_neck_comp = 0.12
        self.thresh_forward_jut = 0.045
        self.thresh_lateral_deg = 10.5
        self.hysteresis_exit_ratio = 0.62

        # Runtime Stats & Flags
        self.slouch_start_time = None
        self.hand_face_start_time = None
        self.in_slouch_state = False
        self.upright_seconds = 0.0
        self.total_tracked_seconds = 0.0
        self.slouch_event_count = 0
        self.last_frame_time = time.time()
        self.chime_played_for_current_slouch = False
        self.audio_enabled = True
        self.show_overlay_guides = True

        # Passive Culprit App Analytics (polled max 2x/sec only during slouching)
        self.slouch_seconds_by_app = {}
        self.last_app_poll_time = 0.0
        self.cached_app_name = None
        self.top_culprit_summary = "No slouch triggers recorded yet"

        # Load saved settings before UI builds widgets
        saved = load_saved_profile()
        if saved:
            self.baseline_neck_ratio = saved.get("baseline_neck_ratio")
            self.baseline_z_diff = saved.get("baseline_z_diff")
            self.baseline_lateral_deg = saved.get("baseline_lateral_deg", 0.0)
            self.slouch_delay_sec = saved.get("slouch_delay_sec", 1.8)
            self.overlay.max_opacity = saved.get("max_opacity", 0.72)
            self.audio_enabled = saved.get("audio_enabled", True)
            self.show_overlay_guides = saved.get("show_overlay_guides", True)
            if saved.get("use_acrylic_blur", False):
                self.overlay.use_acrylic_blur = True

        # Telemetry
        self.lock = threading.Lock()
        self.latest_frame_rgb = None
        self.comp_ratio = 0.0
        self.jut_ratio = 0.0
        self.lat_ratio = 0.0
        self.neck_compression_pct = 0.0
        self.forward_jut_cm = 0.0
        self.lateral_lean_deg = 0.0
        self.is_slouching = False
        self.slouch_reason = ""
        self.status_text = "Ready to calibrate"
        self.status_type = "info"
        self.target_dim_intensity = 0.0
        self.session_score_pct = 100.0
        self.stealth_active = False

        self.trigger_calibrate = False

    def request_calibration(self):
        self.trigger_calibrate = True

    def _format_culprit_summary(self) -> str:
        if not self.slouch_seconds_by_app:
            return "No slouch triggers recorded yet"
        total_s = max(sum(self.slouch_seconds_by_app.values()), 0.1)
        top_items = sorted(self.slouch_seconds_by_app.items(), key=lambda x: x[1], reverse=True)[:2]
        parts = [f"{name} ({int(round((secs / total_s) * 100))}%)" for name, secs in top_items]
        return "Top slouch triggers: " + " · ".join(parts)

    def run(self):
        self.pose_detector = PoseDetectorWrapper()
        self.cap = cv2.VideoCapture(0)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        while self.running and self.cap.isOpened():
            now = time.time()
            dt = min(now - self.last_frame_time, 0.5)
            self.last_frame_time = now

            if self.paused:
                time.sleep(0.1)
                continue

            ret, frame = self.cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            frame = cv2.flip(frame, 1)
            h, w, _ = frame.shape
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            img_lm, world_lm = self.pose_detector.process(rgb_frame)

            neck_ratio, z_diff, lateral_deg, hand_near_face = None, None, None, False
            target_dim = 0.0
            reason = ""
            status_str = "Position body in frame"
            status_t = "info"
            slouching_now = False

            if img_lm is not None and world_lm is not None:
                neck_ratio, z_diff, lateral_deg, hand_near_face = self.analyzer.compute(world_lm, img_lm)

                if self.show_overlay_guides:
                    pts = [7, 8, 11, 12]
                    coords = [(int(img_lm[i].x * w), int(img_lm[i].y * h)) for i in pts]
                    guide_color = (209, 52, 56) if self.in_slouch_state else (87, 168, 119)
                    cv2.line(frame, coords[0], coords[2], (180, 180, 180), 2, cv2.LINE_AA)
                    cv2.line(frame, coords[1], coords[3], (180, 180, 180), 2, cv2.LINE_AA)
                    cv2.line(frame, coords[2], coords[3], guide_color, 2, cv2.LINE_AA)
                    for pt in coords:
                        cv2.circle(frame, pt, 4, (245, 245, 245), -1, cv2.LINE_AA)

                if self.trigger_calibrate:
                    self.trigger_calibrate = False
                    if neck_ratio is not None and z_diff is not None:
                        self.baseline_neck_ratio = neck_ratio
                        self.baseline_z_diff = z_diff
                        self.baseline_lateral_deg = lateral_deg
                        self.slouch_start_time = None
                        self.in_slouch_state = False
                        save_profile({
                            "baseline_neck_ratio": round(neck_ratio, 5),
                            "baseline_z_diff": round(z_diff, 5),
                            "baseline_lateral_deg": round(lateral_deg, 3),
                            "slouch_delay_sec": self.slouch_delay_sec,
                            "use_acrylic_blur": self.overlay.use_acrylic_blur,
                            "max_opacity": self.overlay.max_opacity,
                            "audio_enabled": self.audio_enabled,
                            "show_overlay_guides": self.show_overlay_guides,
                        })

                if self.baseline_neck_ratio is not None and neck_ratio is not None:
                    self.total_tracked_seconds += dt
                    neck_comp = max(0.0, (self.baseline_neck_ratio - neck_ratio) / self.baseline_neck_ratio)
                    fwd_jut = max(0.0, z_diff - self.baseline_z_diff)
                    lat_lean = max(0.0, lateral_deg - self.baseline_lateral_deg)

                    c_ratio = neck_comp / self.thresh_neck_comp
                    j_ratio = fwd_jut / self.thresh_forward_jut
                    l_ratio = lat_lean / self.thresh_lateral_deg
                    max_metric = max(c_ratio, j_ratio, l_ratio)

                    if hand_near_face:
                        if self.hand_face_start_time is None:
                            self.hand_face_start_time = now
                        hand_elapsed = now - self.hand_face_start_time
                    else:
                        self.hand_face_start_time = None
                        hand_elapsed = 0.0

                    if not self.in_slouch_state and max_metric >= 1.0:
                        self.in_slouch_state = True
                        self.slouch_event_count += 1
                        self.chime_played_for_current_slouch = False
                    elif self.in_slouch_state and max_metric < self.hysteresis_exit_ratio and hand_elapsed < self.hand_pause_max_sec:
                        self.in_slouch_state = False

                    if hand_near_face and hand_elapsed < self.hand_pause_max_sec and not self.in_slouch_state:
                        self.slouch_start_time = None
                        self.upright_seconds += dt
                        status_str = f"Temporary movement ({hand_elapsed:.1f}s)"
                        status_t = "activity"
                    elif self.in_slouch_state or (hand_near_face and hand_elapsed >= self.hand_pause_max_sec):
                        slouching_now = True
                        if hand_near_face and hand_elapsed >= self.hand_pause_max_sec:
                            reason = "Hand supporting chin"
                        elif c_ratio >= j_ratio and c_ratio >= l_ratio:
                            reason = f"Spine compression ({neck_comp*100:.0f}%)"
                        elif j_ratio >= l_ratio:
                            reason = f"Head leaning forward (+{fwd_jut*100:.1f} cm)"
                        else:
                            reason = f"Shoulder tilt ({lat_lean:.1f}°)"

                        if self.slouch_start_time is None:
                            self.slouch_start_time = now
                        elapsed = now - self.slouch_start_time

                        if elapsed >= self.slouch_delay_sec:
                            overtime = elapsed - self.slouch_delay_sec
                            target_dim = min(overtime / 2.8, 1.0)
                            status_str = f"Slouching: {reason}"
                            status_t = "slouch"

                            # Passively log foreground app (polled only every 0.5s)
                            if now - self.last_app_poll_time >= 0.5:
                                self.last_app_poll_time = now
                                self.cached_app_name = get_active_app_name()
                            if self.cached_app_name:
                                self.slouch_seconds_by_app[self.cached_app_name] = (
                                    self.slouch_seconds_by_app.get(self.cached_app_name, 0.0) + dt
                                )

                            if self.audio_enabled and not self.chime_played_for_current_slouch and elapsed >= 3.0:
                                self.chime_played_for_current_slouch = True
                                try:
                                    winsound.MessageBeep(winsound.MB_ICONASTERISK)
                                except Exception:
                                    pass
                        else:
                            status_str = f"Posture slipping ({self.slouch_delay_sec - elapsed:.1f}s)"
                            status_t = "warning"
                    else:
                        self.slouch_start_time = None
                        self.upright_seconds += dt
                        target_dim = 0.0
                        status_str = "Good posture"
                        status_t = "optimal"

                    with self.lock:
                        self.comp_ratio = c_ratio
                        self.jut_ratio = j_ratio
                        self.lat_ratio = l_ratio
                        self.neck_compression_pct = neck_comp * 100.0
                        self.forward_jut_cm = fwd_jut * 100.0
                        self.lateral_lean_deg = lat_lean
                else:
                    status_str = "Click 'Calibrate baseline' to begin"
                    status_t = "info"

            self.overlay.update_intensity(target_dim, reason)

            display_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            score = (self.upright_seconds / max(self.total_tracked_seconds, 1.0)) * 100.0
            culprit_str = self._format_culprit_summary()

            with self.lock:
                self.latest_frame_rgb = display_rgb
                self.is_slouching = slouching_now
                self.slouch_reason = reason
                self.status_text = status_str
                self.status_type = status_t
                self.target_dim_intensity = target_dim
                self.session_score_pct = score
                self.top_culprit_summary = culprit_str

            if self.stealth_active and not slouching_now:
                time.sleep(0.18)
            else:
                time.sleep(0.01)

        self.cap.release()


# =====================================================================
#  CLEAN, HUMAN-DESIGNED WINDOWS 11 DESKTOP APP (RESTORED 960x650)
# =====================================================================
class PostureGuardianApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Posture Guardian")
        self.geometry("960x650")
        self.minsize(880, 580)
        self.configure(fg_color="#202020")

        # Win32 Click-through background overlay
        self.overlay = WindowsDesktopBiofeedback(parent=self)

        # Worker thread
        self.worker = VisionWorker(overlay=self.overlay)
        self.worker.start()

        self.stealth_mode = False
        self.last_tray_state = None
        self.current_ctk_img = None

        self._build_header()
        self._build_content()
        self._build_footer()
        self._init_tray()

        self.protocol("WM_DELETE_WINDOW", self.minimize_to_tray)
        self.after(30, self._ui_tick)
        self.after(60, self._check_hotkeys)

    def _build_header(self):
        header = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=8, height=54, border_width=1, border_color="#383838")
        header.pack(fill="x", padx=16, pady=(14, 8))
        header.pack_propagate(False)

        left_box = ctk.CTkFrame(header, fg_color="transparent")
        left_box.pack(side="left", padx=14, pady=8)

        ctk.CTkLabel(
            left_box,
            text="Posture Guardian",
            font=ctk.CTkFont(family="Segoe UI", size=15, weight="bold"),
            text_color="#ffffff"
        ).pack(side="left", padx=(0, 10))

        self.status_badge = ctk.CTkLabel(
            left_box,
            text="● Good posture",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#57a877",
            fg_color="#243429",
            corner_radius=4,
            padx=10,
            pady=3
        )
        self.status_badge.pack(side="left")

        right_box = ctk.CTkFrame(header, fg_color="transparent")
        right_box.pack(side="right", padx=12)

        self.btn_calib = ctk.CTkButton(
            right_box,
            text="Calibrate baseline",
            command=self.on_calibrate,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#0067c0",
            hover_color="#1979c9",
            corner_radius=4,
            height=30,
            width=135
        )
        self.btn_calib.pack(side="left", padx=5)

        self.btn_stealth = ctk.CTkButton(
            right_box,
            text="Hide camera",
            command=self.on_toggle_stealth,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#383838",
            hover_color="#444444",
            text_color="#e0e0e0",
            corner_radius=4,
            height=30,
            width=100
        )
        self.btn_stealth.pack(side="left", padx=5)

        btn_min = ctk.CTkButton(
            right_box,
            text="Minimize to tray",
            command=self.minimize_to_tray,
            font=ctk.CTkFont(family="Segoe UI", size=12),
            fg_color="#383838",
            hover_color="#444444",
            text_color="#e0e0e0",
            corner_radius=4,
            height=30,
            width=115
        )
        btn_min.pack(side="left", padx=5)

    def _build_content(self):
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=16, pady=4)

        # LEFT: Camera Card
        left_card = ctk.CTkFrame(content, fg_color="#2b2b2b", corner_radius=8, border_width=1, border_color="#383838")
        left_card.pack(side="left", fill="both", expand=True, padx=(0, 8))

        card_title_row = ctk.CTkFrame(left_card, fg_color="transparent")
        card_title_row.pack(fill="x", padx=14, pady=(12, 6))

        ctk.CTkLabel(
            card_title_row,
            text="Camera",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#ffffff"
        ).pack(side="left")

        self.lbl_cam_status = ctk.CTkLabel(
            card_title_row,
            text="Live 30 FPS",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#9e9e9e"
        )
        self.lbl_cam_status.pack(side="right")

        self.video_box = ctk.CTkLabel(
            left_card,
            text="Connecting to webcam...",
            font=ctk.CTkFont(family="Segoe UI", size=12),
            text_color="#888888",
            fg_color="#181818",
            corner_radius=6
        )
        self.video_box.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        cam_tools = ctk.CTkFrame(left_card, fg_color="transparent")
        cam_tools.pack(fill="x", padx=14, pady=(0, 12))

        self.chk_guides = ctk.CTkCheckBox(
            cam_tools,
            text="Show alignment guides",
            command=self.on_toggle_guides,
            font=ctk.CTkFont(family="Segoe UI", size=11),
            fg_color="#0067c0",
            hover_color="#1979c9",
            corner_radius=3,
            checkbox_width=18,
            checkbox_height=18
        )
        self.chk_guides.pack(side="left")
        if self.worker.show_overlay_guides:
            self.chk_guides.select()

        ctk.CTkLabel(
            cam_tools,
            text="Shortcut: Alt+C to recalibrate",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#808080"
        ).pack(side="right")

        # RIGHT: Posture Metrics & Warning Settings
        right_frame = ctk.CTkFrame(content, fg_color="transparent", width=380)
        right_frame.pack(side="right", fill="both", padx=(8, 0))
        right_frame.pack_propagate(False)

        # 1. Posture Status & Metrics Card
        metrics_card = ctk.CTkFrame(right_frame, fg_color="#2b2b2b", corner_radius=8, border_width=1, border_color="#383838")
        metrics_card.pack(fill="x", pady=(0, 10))

        ctk.CTkLabel(
            metrics_card,
            text="Current posture",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#ffffff"
        ).pack(anchor="w", padx=14, pady=(12, 6))

        score_row = ctk.CTkFrame(metrics_card, fg_color="#222222", corner_radius=6)
        score_row.pack(fill="x", padx=14, pady=(0, 10))

        self.lbl_score_num = ctk.CTkLabel(
            score_row,
            text="95%",
            font=ctk.CTkFont(family="Segoe UI", size=28, weight="bold"),
            text_color="#57a877"
        )
        self.lbl_score_num.pack(side="left", padx=14, pady=8)

        score_detail = ctk.CTkFrame(score_row, fg_color="transparent")
        score_detail.pack(side="left", fill="both", expand=True, pady=6)

        ctk.CTkLabel(
            score_detail,
            text="Upright posture today",
            font=ctk.CTkFont(family="Segoe UI", size=11, weight="bold"),
            text_color="#e0e0e0"
        ).pack(anchor="w")

        self.lbl_session_times = ctk.CTkLabel(
            score_detail,
            text="0m upright · 0 slouch alerts",
            font=ctk.CTkFont(family="Segoe UI", size=11),
            text_color="#9e9e9e"
        )
        self.lbl_session_times.pack(anchor="w")

        self.lbl_culprits = ctk.CTkLabel(
            score_detail,
            text="No slouch triggers recorded yet",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color="#5b9bd5"
        )
        self.lbl_culprits.pack(anchor="w")

        # Telemetry Progress Rows
        telemetry_box = ctk.CTkFrame(metrics_card, fg_color="transparent")
        telemetry_box.pack(fill="x", padx=14, pady=(0, 12))

        self.lbl_spine = ctk.CTkLabel(telemetry_box, text="Spine compression: 0%", font=ctk.CTkFont(size=11), text_color="#cccccc")
        self.lbl_spine.pack(anchor="w", pady=(2, 2))
        self.bar_spine = ctk.CTkProgressBar(telemetry_box, height=6, corner_radius=3, fg_color="#3a3a3a", progress_color="#57a877")
        self.bar_spine.pack(fill="x", pady=(0, 6))
        self.bar_spine.set(0.0)

        self.lbl_jut = ctk.CTkLabel(telemetry_box, text="Forward head: 0.0 cm", font=ctk.CTkFont(size=11), text_color="#cccccc")
        self.lbl_jut.pack(anchor="w", pady=(2, 2))
        self.bar_jut = ctk.CTkProgressBar(telemetry_box, height=6, corner_radius=3, fg_color="#3a3a3a", progress_color="#57a877")
        self.bar_jut.pack(fill="x", pady=(0, 6))
        self.bar_jut.set(0.0)

        self.lbl_lean = ctk.CTkLabel(telemetry_box, text="Shoulder balance: 0.0°", font=ctk.CTkFont(size=11), text_color="#cccccc")
        self.lbl_lean.pack(anchor="w", pady=(2, 2))
        self.bar_lean = ctk.CTkProgressBar(telemetry_box, height=6, corner_radius=3, fg_color="#3a3a3a", progress_color="#57a877")
        self.bar_lean.pack(fill="x", pady=(0, 2))
        self.bar_lean.set(0.0)

        # 2. Warning Settings Card
        settings_card = ctk.CTkFrame(right_frame, fg_color="#2b2b2b", corner_radius=8, border_width=1, border_color="#383838")
        settings_card.pack(fill="both", expand=True)

        ctk.CTkLabel(
            settings_card,
            text="Screen warning settings",
            font=ctk.CTkFont(family="Segoe UI", size=14, weight="bold"),
            text_color="#ffffff"
        ).pack(anchor="w", padx=14, pady=(12, 8))

        ctk.CTkLabel(settings_card, text="Feedback effect", font=ctk.CTkFont(size=11), text_color="#9e9e9e").pack(anchor="w", padx=14)
        self.seg_mode = ctk.CTkSegmentedButton(
            settings_card,
            values=["Screen dimming", "Acrylic blur"],
            command=self.on_mode_change,
            selected_color="#0067c0",
            selected_hover_color="#1979c9",
            corner_radius=4,
            height=28
        )
        self.seg_mode.pack(fill="x", padx=14, pady=(3, 10))
        self.seg_mode.set("Acrylic blur" if self.overlay.use_acrylic_blur else "Screen dimming")

        self.lbl_grace = ctk.CTkLabel(settings_card, text=f"Delay before warning: {self.worker.slouch_delay_sec:.1f} s", font=ctk.CTkFont(size=11), text_color="#9e9e9e")
        self.lbl_grace.pack(anchor="w", padx=14)
        self.slider_delay = ctk.CTkSlider(
            settings_card,
            from_=1.0,
            to=4.0,
            number_of_steps=30,
            command=self.on_delay_change,
            progress_color="#0067c0",
            height=16
        )
        self.slider_delay.pack(fill="x", padx=14, pady=(2, 10))
        self.slider_delay.set(self.worker.slouch_delay_sec)

        self.lbl_dim_level = ctk.CTkLabel(settings_card, text=f"Maximum dim level: {int(self.overlay.max_opacity*100)}%", font=ctk.CTkFont(size=11), text_color="#9e9e9e")
        self.lbl_dim_level.pack(anchor="w", padx=14)
        self.slider_opacity = ctk.CTkSlider(
            settings_card,
            from_=0.40,
            to=0.90,
            number_of_steps=25,
            command=self.on_opacity_change,
            progress_color="#0067c0",
            height=16
        )
        self.slider_opacity.pack(fill="x", padx=14, pady=(2, 10))
        self.slider_opacity.set(self.overlay.max_opacity)

        self.switch_sound = ctk.CTkSwitch(
            settings_card,
            text="Play chime on persistent slouch",
            command=self.on_sound_toggle,
            font=ctk.CTkFont(size=11),
            progress_color="#0067c0",
            switch_width=38,
            switch_height=20
        )
        self.switch_sound.pack(anchor="w", padx=14, pady=(2, 10))
        if self.worker.audio_enabled:
            self.switch_sound.select()
        else:
            self.switch_sound.deselect()

        btn_preview = ctk.CTkButton(
            settings_card,
            text="Preview warning effect",
            command=self.preview_effect,
            font=ctk.CTkFont(size=11),
            fg_color="#383838",
            hover_color="#444444",
            text_color="#e0e0e0",
            corner_radius=4,
            height=28
        )
        btn_preview.pack(fill="x", padx=14, pady=(0, 10))

    def _build_footer(self):
        footer = ctk.CTkFrame(self, fg_color="#1c1c1c", height=28, corner_radius=0)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)

        ctk.CTkLabel(
            footer,
            text="Global shortcuts:  Alt+C Calibrate  ·  Alt+B Toggle mode  ·  Alt+H Hide camera  ·  Alt+Q Quit",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color="#777777"
        ).pack(side="left", padx=16)

        ctk.CTkLabel(
            footer,
            text="Settings saved to posture_profile.json",
            font=ctk.CTkFont(family="Segoe UI", size=10),
            text_color="#777777"
        ).pack(side="right", padx=16)

    # -----------------------------------------------------------------
    # ACTIONS & EVENT HANDLERS
    # -----------------------------------------------------------------
    def on_calibrate(self):
        self.worker.request_calibration()
        self.btn_calib.configure(text="Calibrated", fg_color="#28a745")
        self.after(1400, lambda: self.btn_calib.configure(text="Calibrate baseline", fg_color="#0067c0"))

    def on_toggle_stealth(self):
        self.stealth_mode = not self.stealth_mode
        self.worker.stealth_active = self.stealth_mode
        if self.stealth_mode:
            self.btn_stealth.configure(text="Show camera", fg_color="#28a745", text_color="#ffffff")
            self.lbl_cam_status.configure(text="Battery-saver mode (5 FPS)")
            self.current_ctk_img = None
            try:
                self.video_box._label.configure(image="")
            except Exception:
                pass
            self.video_box.configure(
                image=None,
                text="Camera paused\nBackground monitoring continues at 5 FPS to conserve battery."
            )
        else:
            self.btn_stealth.configure(text="Hide camera", fg_color="#383838", text_color="#e0e0e0")
            self.lbl_cam_status.configure(text="Live 30 FPS")
            try:
                self.video_box._label.configure(image="")
            except Exception:
                pass
            self.video_box.configure(text="", image=None)

    def on_toggle_guides(self):
        self.worker.show_overlay_guides = bool(self.chk_guides.get())
        self._save_settings()

    def on_mode_change(self, mode_name):
        self.overlay.use_acrylic_blur = (mode_name == "Acrylic blur")
        self._save_settings()

    def on_delay_change(self, val):
        self.worker.slouch_delay_sec = round(float(val), 1)
        self.lbl_grace.configure(text=f"Delay before warning: {self.worker.slouch_delay_sec:.1f} s")
        self._save_settings()

    def on_opacity_change(self, val):
        self.overlay.max_opacity = round(float(val), 2)
        self.lbl_dim_level.configure(text=f"Maximum dim level: {int(self.overlay.max_opacity*100)}%")
        self._save_settings()

    def on_sound_toggle(self):
        self.worker.audio_enabled = bool(self.switch_sound.get())
        self._save_settings()

    def preview_effect(self):
        self.overlay.update_intensity(1.0, "Preview mode")
        self.after(2200, lambda: self.overlay.update_intensity(0.0, ""))

    def _save_settings(self):
        save_profile({
            "baseline_neck_ratio": self.worker.baseline_neck_ratio,
            "baseline_z_diff": self.worker.baseline_z_diff,
            "baseline_lateral_deg": self.worker.baseline_lateral_deg,
            "slouch_delay_sec": self.worker.slouch_delay_sec,
            "use_acrylic_blur": self.overlay.use_acrylic_blur,
            "max_opacity": self.overlay.max_opacity,
            "audio_enabled": self.worker.audio_enabled,
            "show_overlay_guides": self.worker.show_overlay_guides,
        })

    # -----------------------------------------------------------------
    # UI UPDATE TICK (30 FPS)
    # -----------------------------------------------------------------
    def _ui_tick(self):
        with self.worker.lock:
            frame_rgb = self.worker.latest_frame_rgb
            comp_r = self.worker.comp_ratio
            jut_r = self.worker.jut_ratio
            lat_r = self.worker.lat_ratio
            comp_pct = self.worker.neck_compression_pct
            jut_cm = self.worker.forward_jut_cm
            lat_deg = self.worker.lateral_lean_deg
            is_slouch = self.worker.is_slouching
            status_txt = self.worker.status_text
            status_t = self.worker.status_type
            score = self.worker.session_score_pct
            upright_s = self.worker.upright_seconds
            slouch_cnt = self.worker.slouch_event_count
            culprit_txt = self.worker.top_culprit_summary

        if not self.stealth_mode and frame_rgb is not None and self.winfo_viewable():
            try:
                cw = max(self.video_box.winfo_width(), 440)
                ch = max(self.video_box.winfo_height(), 250)
                img = Image.fromarray(frame_rgb)
                img.thumbnail((cw, ch), Image.Resampling.LANCZOS)
                self.current_ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=img.size)
                self.video_box.configure(image=self.current_ctk_img, text="")
            except Exception:
                try:
                    self.video_box._label.configure(image="")
                except Exception:
                    pass

        if status_t == "optimal":
            self.status_badge.configure(text="● Good posture", text_color="#57a877", fg_color="#243429")
        elif status_t == "slouch":
            self.status_badge.configure(text=f"● {status_txt}", text_color="#d13438", fg_color="#3a1e20")
        elif status_t == "warning":
            self.status_badge.configure(text=f"● {status_txt}", text_color="#dca452", fg_color="#3b3020")
        elif status_t == "activity":
            self.status_badge.configure(text=f"● {status_txt}", text_color="#5b9bd5", fg_color="#1e293b")
        else:
            self.status_badge.configure(text=f"● {status_txt}", text_color="#9e9e9e", fg_color="#2d2d2d")

        self.lbl_spine.configure(text=f"Spine compression: {comp_pct:.0f}%")
        self.bar_spine.set(min(comp_r, 1.0))
        self.bar_spine.configure(progress_color="#d13438" if comp_r >= 1.0 else ("#dca452" if comp_r >= 0.65 else "#57a877"))

        self.lbl_jut.configure(text=f"Forward head posture: +{jut_cm:.1f} cm")
        self.bar_jut.set(min(jut_r, 1.0))
        self.bar_jut.configure(progress_color="#d13438" if jut_r >= 1.0 else ("#dca452" if jut_r >= 0.65 else "#57a877"))

        self.lbl_lean.configure(text=f"Shoulder balance: {lat_deg:.1f}°")
        self.bar_lean.set(min(lat_r, 1.0))
        self.bar_lean.configure(progress_color="#d13438" if lat_r >= 1.0 else ("#dca452" if lat_r >= 0.65 else "#57a877"))

        self.lbl_score_num.configure(text=f"{score:.0f}%")
        self.lbl_score_num.configure(text_color="#57a877" if score >= 85 else ("#dca452" if score >= 70 else "#d13438"))
        self.lbl_session_times.configure(text=f"{int(upright_s//60)}m upright · {slouch_cnt} slouch alerts")
        self.lbl_culprits.configure(text=culprit_txt)

        if is_slouch != self.last_tray_state:
            self.last_tray_state = is_slouch
            try:
                self.tray_icon.icon = create_tray_image(is_slouch)
                self.tray_icon.title = "Posture Guardian: Slouching" if is_slouch else "Posture Guardian: Good posture"
            except Exception:
                pass

        self.after(30, self._ui_tick)

    # -----------------------------------------------------------------
    # GLOBAL KEYBOARD SHORTCUTS (Alt+C, Alt+B, Alt+H, Alt+Q)
    # -----------------------------------------------------------------
    def _check_hotkeys(self):
        user32 = ctypes.windll.user32
        alt_held = (user32.GetAsyncKeyState(0x12) & 0x8000) != 0

        if alt_held:
            if user32.GetAsyncKeyState(0x43) & 0x0001:  # Alt+C
                self.on_calibrate()
            elif user32.GetAsyncKeyState(0x42) & 0x0001:  # Alt+B
                new_m = "Acrylic blur" if self.seg_mode.get() == "Screen dimming" else "Screen dimming"
                self.seg_mode.set(new_m)
                self.on_mode_change(new_m)
            elif user32.GetAsyncKeyState(0x48) & 0x0001:  # Alt+H
                self.on_toggle_stealth()
            elif user32.GetAsyncKeyState(0x51) & 0x0001:  # Alt+Q
                self.quit_app()

        self.after(60, self._check_hotkeys)

    # -----------------------------------------------------------------
    # SYSTEM TRAY
    # -----------------------------------------------------------------
    def _init_tray(self):
        tray_menu = pystray.Menu(
            pystray.MenuItem("Show Posture Guardian", lambda icon, item: self.after(0, self.restore_from_tray), default=True),
            pystray.MenuItem("Calibrate baseline", lambda icon, item: self.after(0, self.on_calibrate)),
            pystray.MenuItem("Hide / Show camera", lambda icon, item: self.after(0, self.on_toggle_stealth)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Exit", lambda icon, item: self.after(0, self.quit_app)),
        )
        self.tray_icon = pystray.Icon(
            "PostureGuardian",
            create_tray_image(False),
            "Posture Guardian: Good posture",
            tray_menu
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def minimize_to_tray(self):
        self.withdraw()

    def restore_from_tray(self, icon=None, item=None):
        self.deiconify()
        self.lift()
        self.focus_force()

    def quit_app(self):
        self.worker.running = False
        try:
            self.tray_icon.stop()
        except Exception:
            pass
        self.overlay.close()
        self.destroy()
        sys.exit(0)


def main():
    app = PostureGuardianApp()
    app.mainloop()


if __name__ == "__main__":
    import multiprocessing
    multiprocessing.freeze_support()
    main()