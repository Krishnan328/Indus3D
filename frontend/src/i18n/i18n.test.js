import { describe, it } from "node:test";
import assert from "node:assert/strict";
import { t, setLanguage, getLanguage, SUPPORTED_LANGUAGES } from "./i18n.js";

describe("i18n translation engine", () => {
  it("translates English keys by default", () => {
    assert.equal(t("nav.dashboard", {}, "en"), "Dashboard");
    assert.equal(t("common.emergencyStop", {}, "en"), "EMERGENCY STOP");
  });

  it("translates German keys", () => {
    assert.equal(t("nav.dashboard", {}, "de"), "Übersicht");
    assert.equal(t("common.emergencyStop", {}, "de"), "NOT-AUS");
  });

  it("translates French keys", () => {
    assert.equal(t("nav.dashboard", {}, "fr"), "Tableau de bord");
    assert.equal(t("common.emergencyStop", {}, "fr"), "ARRÊT D'URGENCE");
  });

  it("translates Chinese keys", () => {
    assert.equal(t("nav.dashboard", {}, "zh"), "仪表板");
    assert.equal(t("common.emergencyStop", {}, "zh"), "紧急停止");
  });

  it("falls back to English when key is missing in another language", () => {
    assert.equal(t("nonexistent.key", {}, "de"), "nonexistent.key");
  });

  it("interpolates parameters", () => {
    const text = t("common.welcome", { name: "Antigravity" }, "en");
    // If key doesn't exist, returns key
    assert.equal(text, "common.welcome");
  });

  it("sets and gets active language", () => {
    setLanguage("fr");
    assert.equal(getLanguage(), "fr");
    setLanguage("en");
    assert.equal(getLanguage(), "en");
  });
});
