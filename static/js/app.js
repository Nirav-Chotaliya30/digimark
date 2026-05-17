(() => {
  const storageKey = "digimark-theme";
  const body = document.body;
  const themeToggleBtn = document.getElementById("themeToggleBtn");
  const toastContainer = document.getElementById("toastContainer");
  const appShell = document.getElementById("appShell");
  const sidebarToggleBtn = document.getElementById("sidebarToggleBtn");
  const sidebarCloseBtn = document.getElementById("sidebarCloseBtn");
  const sidebarOverlay = document.getElementById("sidebarOverlay");

  function applyTheme(theme) {
    body.setAttribute("data-bs-theme", theme);
    if (themeToggleBtn) {
      themeToggleBtn.innerHTML = theme === "dark" ? '<i class="fa-regular fa-sun"></i>' : '<i class="fa-regular fa-moon"></i>';
    }
  }

  const savedTheme = localStorage.getItem(storageKey) || "light";
  applyTheme(savedTheme);

  if (themeToggleBtn) {
    themeToggleBtn.addEventListener("click", () => {
      const nextTheme = body.getAttribute("data-bs-theme") === "dark" ? "light" : "dark";
      localStorage.setItem(storageKey, nextTheme);
      applyTheme(nextTheme);
    });
  }

  const toggleSidebar = (open) => {
    if (!appShell) return;
    appShell.classList.toggle("sidebar-open", Boolean(open));
  };
  sidebarToggleBtn?.addEventListener("click", () => toggleSidebar(true));
  sidebarCloseBtn?.addEventListener("click", () => toggleSidebar(false));
  sidebarOverlay?.addEventListener("click", () => toggleSidebar(false));

  const logoutLinks = document.querySelectorAll(".js-logout-link");
  if (logoutLinks.length) {
    const modalEl = document.getElementById("logoutModal");
    const confirmBtn = document.getElementById("confirmLogoutBtn");
    const modal = modalEl ? new bootstrap.Modal(modalEl) : null;
    logoutLinks.forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        if (confirmBtn) {
          confirmBtn.setAttribute("href", link.getAttribute("href"));
        }
        if (modal) {
          modal.show();
        } else {
          window.location.href = link.getAttribute("href");
        }
      });
    });
  }

  window.showToast = (message, variant = "success") => {
    if (!toastContainer) {
      return;
    }
    const wrapper = document.createElement("div");
    wrapper.className = `toast align-items-center text-bg-${variant} border-0`;
    wrapper.setAttribute("role", "alert");
    wrapper.setAttribute("aria-live", "assertive");
    wrapper.setAttribute("aria-atomic", "true");
    wrapper.innerHTML = `
      <div class="d-flex">
        <div class="toast-body">${message}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button>
      </div>
    `;
    toastContainer.appendChild(wrapper);
    const toast = new bootstrap.Toast(wrapper, { delay: 2600 });
    toast.show();
    wrapper.addEventListener("hidden.bs.toast", () => wrapper.remove());
  };

  window.confirmAction = (message) => window.confirm(message);
})();
