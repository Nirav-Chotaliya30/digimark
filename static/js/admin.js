(() => {
  async function apiRequest(url, options = {}) {
    try {
      const response = await fetch(url, options);
      let payload = { success: false, message: "Unexpected response from server." };
      try {
        payload = await response.json();
      } catch (_) {
        payload = { success: false, message: `Request failed with status ${response.status}.` };
      }
      if (!response.ok && payload.success !== false) {
        payload.success = false;
        payload.message = payload.message || `Request failed with status ${response.status}.`;
      }
      return payload;
    } catch (_) {
      return { success: false, message: "Network error. Please try again." };
    }
  }

  function wireTableSearch({ searchInputId, tableBodySelector, branchFilterId = null, branchDataKey = "branch", searchDataKey = "search", subjectFilterId = null, subjectDataKey = "subject", dateFilterId = null, dateDataKey = "date" }) {
    const searchInput = document.getElementById(searchInputId);
    const branchFilter = branchFilterId ? document.getElementById(branchFilterId) : null;
    const subjectFilter = subjectFilterId ? document.getElementById(subjectFilterId) : null;
    const dateFilter = dateFilterId ? document.getElementById(dateFilterId) : null;
    const rows = Array.from(document.querySelectorAll(`${tableBodySelector} tr`));
    if (!searchInput || !rows.length) return;

    const applyFilter = () => {
      const query = (searchInput.value || "").toLowerCase();
      const branchValue = branchFilter ? branchFilter.value : "";
      const subjectValue = subjectFilter ? subjectFilter.value : "";
      const dateValue = dateFilter ? dateFilter.value : "";
      rows.forEach((row) => {
        const searchText = String(row.dataset[searchDataKey] || "").toLowerCase();
        const branchOk = !branchValue || row.dataset[branchDataKey] === branchValue;
        const subjectOk = !subjectValue || row.dataset[subjectDataKey] === subjectValue;
        const dateOk = !dateValue || row.dataset[dateDataKey] === dateValue;
        row.classList.toggle("d-none", !(searchText.includes(query) && branchOk && subjectOk && dateOk));
      });
    };

    searchInput.addEventListener("input", applyFilter);
    branchFilter?.addEventListener("change", applyFilter);
    subjectFilter?.addEventListener("change", applyFilter);
    dateFilter?.addEventListener("change", applyFilter);
  }

  function renderBulkResult(targetId, data) {
    const target = document.getElementById(targetId);
    if (!target) return;
    target.innerHTML = `<div class="alert alert-${data.success ? "success" : "danger"} py-2 mb-0">Created ${data.created_count || 0}, Errors ${data.error_count || 0}</div>`;
  }

  window.DigiMarkAdmin = {
    apiRequest,
    wireTableSearch,
    renderBulkResult,
  };
})();
