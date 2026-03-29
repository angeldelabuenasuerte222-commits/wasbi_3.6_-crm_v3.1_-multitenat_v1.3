export const normalizeSlug = (value) => {
  if (!value || typeof value !== "string") {
    return "";
  }
  return value.trim().toLowerCase();
};
