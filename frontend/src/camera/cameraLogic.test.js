import { describe, it } from "node:test";
import assert from "node:assert/strict";
import {
  detectStreamType,
  STREAM_TYPES,
  buildTransformStyle,
  getAspectRatioStyle,
  ASPECT_RATIOS,
  mergeCameras,
} from "./cameraLogic.js";

describe("detectStreamType", () => {
  it("detects WebRTC by service declaration", () => {
    assert.equal(detectStreamType("http://cam:8080/stream", "webrtc-go2rtc"), STREAM_TYPES.WEBRTC);
    assert.equal(detectStreamType("http://cam:8080/stream", "webrtc-camerastreamer"), STREAM_TYPES.WEBRTC);
    assert.equal(detectStreamType("http://cam:8080/stream", "webrtc-janus"), STREAM_TYPES.WEBRTC);
  });

  it("detects WebRTC by URL path", () => {
    assert.equal(detectStreamType("http://cam:8080/webrtc", ""), STREAM_TYPES.WEBRTC);
    assert.equal(detectStreamType("http://cam:8080/api/whep", ""), STREAM_TYPES.WEBRTC);
  });

  it("detects HLS by .m3u8 extension or service", () => {
    assert.equal(detectStreamType("http://cam:8080/live/index.m3u8", ""), STREAM_TYPES.HLS);
    assert.equal(detectStreamType("http://cam:8080/stream", "hls"), STREAM_TYPES.HLS);
  });

  it("detects adaptive MJPEG", () => {
    assert.equal(detectStreamType("http://cam:8080/stream", "mjpegstreamer-adaptive"), STREAM_TYPES.MJPEG_ADAPTIVE);
  });

  it("defaults to standard MJPEG", () => {
    assert.equal(detectStreamType("http://cam:8080/stream", "mjpegstreamer"), STREAM_TYPES.MJPEG);
    assert.equal(detectStreamType("http://cam:8080/video", ""), STREAM_TYPES.MJPEG);
  });
});

describe("buildTransformStyle", () => {
  it("returns none when no rotation and no flip", () => {
    assert.equal(buildTransformStyle(0, false, false), "none");
  });

  it("builds rotation transform", () => {
    assert.equal(buildTransformStyle(90, false, false), "rotate(90deg)");
    assert.equal(buildTransformStyle(180, false, false), "rotate(180deg)");
  });

  it("builds flip transforms", () => {
    assert.equal(buildTransformStyle(0, true, false), "scaleX(-1)");
    assert.equal(buildTransformStyle(0, false, true), "scaleY(-1)");
    assert.equal(buildTransformStyle(0, true, true), "scaleX(-1) scaleY(-1)");
  });

  it("combines rotation and flips", () => {
    assert.equal(buildTransformStyle(180, true, true), "rotate(180deg) scaleX(-1) scaleY(-1)");
  });
});

describe("getAspectRatioStyle", () => {
  it("returns CSS aspect ratio strings", () => {
    assert.equal(getAspectRatioStyle(ASPECT_RATIOS.WIDE), "16 / 9");
    assert.equal(getAspectRatioStyle(ASPECT_RATIOS.STANDARD), "4 / 3");
    assert.equal(getAspectRatioStyle(ASPECT_RATIOS.SQUARE), "1 / 1");
    assert.equal(getAspectRatioStyle(ASPECT_RATIOS.FILL), "auto");
  });
});

describe("mergeCameras", () => {
  it("normalizes discovered cameras", () => {
    const discovered = [
      { name: "Crowsnest", stream_url: "/webcam/stream", flip_horizontal: true },
    ];
    const merged = mergeCameras(discovered, []);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].name, "Crowsnest");
    assert.equal(merged[0].flip_h, true);
    assert.equal(merged[0].flip_v, false);
    assert.equal(merged[0].service, STREAM_TYPES.MJPEG);
  });

  it("applies user overrides on discovered cameras", () => {
    const discovered = [
      { id: "cam1", name: "Nozzle", stream_url: "http://cam1/stream" },
    ];
    const custom = [
      { id: "cam1", rotation: 90, aspect_ratio: "4:3" },
    ];
    const merged = mergeCameras(discovered, custom);
    assert.equal(merged.length, 1);
    assert.equal(merged[0].rotation, 90);
    assert.equal(merged[0].aspect_ratio, "4:3");
  });

  it("appends custom user cameras", () => {
    const discovered = [
      { id: "cam1", name: "Nozzle", stream_url: "http://cam1/stream" },
    ];
    const custom = [
      { id: "cam2", name: "Chamber", stream_url: "http://cam2/stream", service: "webrtc" },
    ];
    const merged = mergeCameras(discovered, custom);
    assert.equal(merged.length, 2);
    assert.equal(merged[1].name, "Chamber");
    assert.equal(merged[1].service, STREAM_TYPES.WEBRTC);
    assert.equal(merged[1].isCustom, true);
  });
});
