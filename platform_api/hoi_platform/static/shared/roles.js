// HOI role avatars: one illustrated badge per department / role (no faces, names or gender; never a staff id).
// Classic script (strict CSP, no build step): window.HOI_AVATAR(department) -> "/shared/avatars/<role>.svg".
(() => {
  "use strict";
  const KNOWN = ["hotel_manager", "front_office", "housekeeping", "fnb_service", "kitchen", "maintenance", "security", "storekeeper"];
  const ALIAS = { manager: "hotel_manager", fnb: "fnb_service", food_beverage: "fnb_service", room_service: "fnb_service", store: "storekeeper", stores: "storekeeper", engineering: "maintenance" };
  window.HOI_AVATAR = (dept) => {
    const k = String(dept || "").trim().toLowerCase();
    return "/shared/avatars/" + (KNOWN.includes(k) ? k : ALIAS[k] || "generic") + ".svg";
  };
  /** Same-origin path only (CSP img-src 'self'); anything else -> null. */
  window.HOI_SAFE_IMG = (u) => (typeof u === "string" && /^\/(?!\/)[\w\-./]+\.(svg|png|jpe?g|webp)$/i.test(u) ? u : null);
})();
