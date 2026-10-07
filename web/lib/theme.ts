export type Theme = "light" | "dark";

/** localStorage key for an explicit light/dark choice. No key means "follow the system setting". */
export const THEME_KEY = "egolabs.theme";

/**
 * Runs in <head> before first paint (see app/layout.tsx) so a stored choice never flashes the other
 * theme. Without a stored choice, globals.css follows the system setting.
 */
export const THEME_SCRIPT = `(function(){try{var t=localStorage.getItem("${THEME_KEY}");if(t==="light"||t==="dark")document.documentElement.setAttribute("data-theme",t)}catch(e){}})()`;
