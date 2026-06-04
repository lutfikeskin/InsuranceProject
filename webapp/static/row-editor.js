// Shared per-row structured editor.
// Used by review_task_detail (review queue) and policy_edit_tab (database).
//
// Markup contract:
//   <form ... onsubmit="serializeReviewRows(this)">
//     <input type="hidden" name="<section>_json" id="<section>_json">
//     <div data-rows="<section>"> <div class="row-card" data-row>... <input data-field="..."> ...</div> </div>
//     <template data-template="<section>"><div class="row-card" data-row>...</div></template>
//     <button type="button" data-add-row="<section>">+</button>
//     <button type="button" data-remove-row>x</button>
//   </form>
//
// data-field supports dotted paths like "limits.per_person" → nested object.
// data-bool="true" parses "true"/"false" to booleans, blank to null.
(function () {
  function setNestedValue(obj, path, value) {
    const parts = path.split('.');
    let cur = obj;
    for (let i = 0; i < parts.length - 1; i++) {
      if (cur[parts[i]] == null) cur[parts[i]] = {};
      cur = cur[parts[i]];
    }
    cur[parts[parts.length - 1]] = value;
  }

  function parseValue(input) {
    const v = input.value;
    if (v === '' || v == null) return null;
    if (input.dataset.bool === 'true') {
      if (v === 'true') return true;
      if (v === 'false') return false;
      return null;
    }
    if (/^-?\d+(\.\d+)?$/.test(String(v).trim())) {
      const num = Number(v);
      if (!Number.isNaN(num)) return num;
    }
    return v;
  }

  function serializeSection(root, sectionName) {
    const container = root.querySelector('[data-rows="' + sectionName + '"]');
    if (!container) return [];
    const rows = container.querySelectorAll('[data-row]');
    const out = [];
    rows.forEach(function (row) {
      const obj = {};
      row.querySelectorAll('[data-field]').forEach(function (input) {
        setNestedValue(obj, input.dataset.field, parseValue(input));
      });
      out.push(obj);
    });
    return out;
  }

  window.serializeReviewRows = function (form) {
    const sections = ['vehicles', 'drivers', 'coverages', 'additional_interests'];
    sections.forEach(function (name) {
      const target = form.querySelector('#' + name + '_json');
      if (target) target.value = JSON.stringify(serializeSection(form, name));
    });
  };

  function bind(root) {
    if (!root || root.dataset.rowEditorBound) return;
    root.dataset.rowEditorBound = '1';
    root.addEventListener('click', function (e) {
      const addBtn = e.target.closest('[data-add-row]');
      if (addBtn) {
        e.preventDefault();
        const name = addBtn.dataset.addRow;
        const tpl = root.querySelector('template[data-template="' + name + '"]');
        const container = root.querySelector('[data-rows="' + name + '"]');
        if (tpl && container) {
          const frag = tpl.content.cloneNode(true);
          container.appendChild(frag);
        }
        return;
      }
      const rmBtn = e.target.closest('[data-remove-row]');
      if (rmBtn) {
        e.preventDefault();
        const row = rmBtn.closest('[data-row]');
        if (row) row.remove();
      }
    });
  }

  function init() {
    document.querySelectorAll('form[id]').forEach(function (form) {
      if (form.querySelector('[data-rows]')) bind(form);
    });
  }

  document.addEventListener('DOMContentLoaded', init);
  document.body && document.body.addEventListener('htmx:afterSwap', init);
})();
