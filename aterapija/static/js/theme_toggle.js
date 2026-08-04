(function () {
  var STORAGE_KEY = "aterapija-theme";
  var LIGHT_THEME = "light";
  var DARK_THEME = "dark";

  function getCurrentTheme() {
    return document.documentElement.getAttribute("data-bs-theme") || LIGHT_THEME;
  }

  function setTheme(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
    try {
      window.localStorage.setItem(STORAGE_KEY, theme);
    } catch (error) {
      // Ignore storage errors (for example private mode restrictions).
    }
    updateToggleUI(theme);
  }

  function updateToggleUI(theme) {
    var toggleButton = document.getElementById("theme-toggle");
    if (!toggleButton) {
      return;
    }

    var sunIcon = toggleButton.querySelector('[data-theme-icon="sun"]');
    var moonIcon = toggleButton.querySelector('[data-theme-icon="moon"]');
    var labelLight = toggleButton.getAttribute("data-label-light") || "Switch to Day mode";
    var labelDark = toggleButton.getAttribute("data-label-dark") || "Switch to Evening mode";

    if (sunIcon) {
      sunIcon.classList.toggle("d-none", theme !== DARK_THEME);
    }
    if (moonIcon) {
      moonIcon.classList.toggle("d-none", theme !== LIGHT_THEME);
    }

    var nextActionLabel = theme === DARK_THEME ? labelLight : labelDark;
    toggleButton.setAttribute("aria-label", nextActionLabel);
    toggleButton.setAttribute("title", nextActionLabel);
  }

  function initThemeToggle() {
    var toggleButton = document.getElementById("theme-toggle");
    if (!toggleButton) {
      return;
    }

    updateToggleUI(getCurrentTheme());

    toggleButton.addEventListener("click", function () {
      var currentTheme = getCurrentTheme();
      var nextTheme = currentTheme === DARK_THEME ? LIGHT_THEME : DARK_THEME;
      setTheme(nextTheme);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initThemeToggle);
  } else {
    initThemeToggle();
  }
})();

