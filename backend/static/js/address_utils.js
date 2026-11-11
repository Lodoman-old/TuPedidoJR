/* Utilidades compartidas para capturar direcciones en toda la web. */
(function () {
  function escapeHtml(value) {
    return String(value == null ? '' : value).replace(/[&<>"']/g, ch => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
    }[ch]));
  }

  function normalize(value) {
    return String(value == null ? '' : value).trim().toLowerCase();
  }

  function pickColonia(names, selected) {
    const list = (names || []).filter(Boolean);
    const wanted = String(selected || '').trim();
    if (!wanted) return list.length === 1 ? list[0] : '';
    const target = normalize(wanted);
    let match = list.find(name => normalize(name) === target);
    if (!match) {
      match = list.find(name => {
        const current = normalize(name);
        return current.includes(target) || target.includes(current);
      });
    }
    if (!match && list.length === 1) match = list[0];
    return match || wanted;
  }

  function fillColoniaSelect(select, names, selected) {
    if (!select) return '';
    const list = (names || []).filter(Boolean);
    const chosen = pickColonia(list, selected);
    if (chosen && !list.includes(chosen)) list.unshift(chosen);
    select.innerHTML = '<option value="">Colonia...</option>' + list.map(name =>
      `<option value="${escapeHtml(name)}" ${name === chosen ? 'selected' : ''}>${escapeHtml(name)}</option>`
    ).join('');
    if (chosen) select.value = chosen;
    return chosen;
  }

  function selectExistingColonia(select, name) {
    if (!select || !name) return '';
    const values = [...select.options].map(option => option.value).filter(Boolean);
    const chosen = pickColonia(values, name);
    let option = [...select.options].find(item => item.value === chosen);
    if (!option) {
      option = document.createElement('option');
      option.value = chosen;
      option.textContent = chosen;
      select.appendChild(option);
    }
    select.value = chosen;
    return chosen;
  }

  function cleanCp(value) {
    return String(value == null ? '' : value).replace(/\D/g, '').slice(0, 5);
  }

  function composeAddress(street, colonia, cp) {
    return [street, colonia, cp ? `C.P. ${cp}` : ''].filter(Boolean).join(', ');
  }

  window.AddressUtils = {
    escapeHtml,
    pickColonia,
    fillColoniaSelect,
    selectExistingColonia,
    cleanCp,
    composeAddress,
  };
})();
