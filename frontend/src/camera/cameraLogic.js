/**
 * cameraLogic.js
 * --------------
 * Pure helper functions for camera stream type detection,
 * CSS transforms, aspect ratio calculations, and camera profile merging.
 */

export const STREAM_TYPES = {
  MJPEG: "mjpeg",
  MJPEG_ADAPTIVE: "mjpeg_adaptive",
  WEBRTC: "webrtc",
  HLS: "hls",
  IFRAME: "iframe",
};

export const ASPECT_RATIOS = {
  WIDE: "16:9",
  STANDARD: "4:3",
  SQUARE: "1:1",
  FILL: "fill",
};

/**
 * Detect stream protocol/type from URL and service declaration.
 */
export function detectStreamType(url = "", declaredService = "") {
  const service = (declaredService || "").toLowerCase();
  const lowerUrl = (url || "").toLowerCase();

  if (service.includes("webrtc") || service.includes("go2rtc") || service.includes("janus")) {
    return STREAM_TYPES.WEBRTC;
  }
  if (service.includes("hls") || lowerUrl.includes(".m3u8")) {
    return STREAM_TYPES.HLS;
  }
  if (service.includes("adaptive")) {
    return STREAM_TYPES.MJPEG_ADAPTIVE;
  }
  if (service.includes("iframe") || lowerUrl.startsWith("http://") && lowerUrl.includes("/embed")) {
    return STREAM_TYPES.IFRAME;
  }
  if (lowerUrl.includes("/webrtc") || lowerUrl.includes("/whep")) {
    return STREAM_TYPES.WEBRTC;
  }
  return STREAM_TYPES.MJPEG;
}

/**
 * Generate CSS transform string for rotation and flipping.
 */
export function buildTransformStyle(rotation = 0, flipH = false, flipV = false) {
  const transforms = [];
  const rot = Number(rotation) || 0;
  if (rot !== 0) {
    transforms.push(`rotate(${rot}deg)`);
  }
  if (flipH) {
    transforms.push("scaleX(-1)");
  }
  if (flipV) {
    transforms.push("scaleY(-1)");
  }
  return transforms.length > 0 ? transforms.join(" ") : "none";
}

/**
 * Get CSS aspect-ratio value.
 */
export function getAspectRatioStyle(aspectRatio = ASPECT_RATIOS.WIDE) {
  switch (aspectRatio) {
    case ASPECT_RATIOS.STANDARD:
      return "4 / 3";
    case ASPECT_RATIOS.SQUARE:
      return "1 / 1";
    case ASPECT_RATIOS.FILL:
      return "auto";
    case ASPECT_RATIOS.WIDE:
    default:
      return "16 / 9";
  }
}

/**
 * Merge discovered cameras with user-defined overrides and custom cameras.
 */
export function mergeCameras(discovered = [], custom = []) {
  const map = new Map();

  // Add discovered
  for (const cam of discovered) {
    const id = cam.id || cam.uid || cam.name || cam.stream_url;
    map.set(id, {
      id,
      name: cam.name || "Camera",
      stream_url: cam.stream_url || cam.url || "",
      snapshot_url: cam.snapshot_url || "",
      service: cam.service || detectStreamType(cam.stream_url),
      rotation: cam.rotation || 0,
      flip_h: Boolean(cam.flip_h || cam.flip_horizontal),
      flip_v: Boolean(cam.flip_v || cam.flip_vertical),
      aspect_ratio: cam.aspect_ratio || ASPECT_RATIOS.WIDE,
      target_fps: cam.target_fps || 15,
      enabled: cam.enabled !== false,
      isCustom: false,
    });
  }

  // Merge or append custom cameras
  for (const c of custom) {
    const id = c.id || c.name || c.stream_url;
    if (map.has(id)) {
      map.set(id, { ...map.get(id), ...c });
    } else {
      map.set(id, {
        id,
        name: c.name || "Custom Camera",
        stream_url: c.stream_url || "",
        snapshot_url: c.snapshot_url || "",
        service: c.service || detectStreamType(c.stream_url),
        rotation: c.rotation || 0,
        flip_h: Boolean(c.flip_h),
        flip_v: Boolean(c.flip_v),
        aspect_ratio: c.aspect_ratio || ASPECT_RATIOS.WIDE,
        target_fps: c.target_fps || 15,
        enabled: c.enabled !== false,
        isCustom: true,
      });
    }
  }

  return Array.from(map.values()).filter((c) => c.enabled !== false);
}

const STORAGE_KEY = "indus3d_custom_cameras_v1";

export function loadUserCameras() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

export function saveUserCameras(cameras = []) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(cameras));
  } catch {
    // quota exceeded or private mode
  }
}
