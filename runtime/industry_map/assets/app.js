/* Untrusted snapshot values cross the DOM boundary only through textContent.
   No fetch: the same embedded snapshot works from file:// and from HTTP. */
(function () {
  'use strict';
  const stages = ['材料', '設備', '製造', '封裝', '測試', '待分類'];
  const copy = value => JSON.parse(JSON.stringify(value));
  function createIndex(snapshot) {
    const index = { snapshot, entities: new Map(), evidence: new Map(), roles: new Map(), relations: new Map(), observations: new Map(), coverage: new Map() };
    const append = (map, key, item) => { if (!map.has(key)) map.set(key, []); map.get(key).push(item); };
    snapshot.entities.forEach(item => index.entities.set(item.id, item));
    snapshot.evidence.forEach(item => index.evidence.set(item.id, item));
    ['roles', 'observations', 'coverage'].forEach(collection => snapshot[collection].forEach(item => append(index[collection], item.company_id, item)));
    snapshot.relations.forEach(item => {
      append(index.relations, item.source_id, item);
      if (item.target_id !== item.source_id) append(index.relations, item.target_id, item);
    });
    return index;
  }
  function filter(index, options = {}) {
    const search = (options.search || '').trim().toLocaleLowerCase();
    const matches = (item, fields) => !search || fields.some(field => String(item[field] || '').toLocaleLowerCase().includes(search));
    const visible = item => options.includePending !== false || item.status !== 'pending';
    const roles = index.snapshot.roles.filter(item => visible(item) && (!options.stage || item.stage === options.stage));
    const eligible = new Set([...index.coverage.keys(), ...index.roles.keys()]);
    const stageIds = new Set(roles.map(item => item.company_id));
    let companies = index.snapshot.entities.filter(item => item.kind === 'company' && eligible.has(item.id) && (!options.stage || stageIds.has(item.id) || (options.stage === '待分類' && !index.roles.has(item.id))));
    const ids = new Set(companies.map(item => item.id));
    const relations = index.snapshot.relations.filter(item => visible(item) && matches(item, ['product', 'predicate']) && (ids.has(item.source_id) || ids.has(item.target_id)));
    const matchingIds = new Set(roles.filter(item => matches(item, ['product', 'stage'])).map(item => item.company_id));
    relations.forEach(item => { matchingIds.add(item.source_id); matchingIds.add(item.target_id); });
    companies = companies.filter(item => matches(item, ['name', 'ticker', 'aliases']) || matchingIds.has(item.id));
    const selected = new Set(companies.map(item => item.id));
    return copy({ companies, roles: roles.filter(item => selected.has(item.company_id) && matches(item, ['product', 'stage'])), relations: relations.filter(item => selected.has(item.source_id) || selected.has(item.target_id)) });
  }
  function select(index, companyId, view = filter(index)) {
    if (!view.companies.some(item => item.id === companyId)) return null;
    const roles = view.roles.filter(item => item.company_id === companyId);
    const relations = view.relations.filter(item => item.source_id === companyId || item.target_id === companyId).map(item => ({ ...item, direction: item.source_id === companyId ? 'outgoing' : 'incoming' }));
    const financials = index.observations.get(companyId) || [];
    const evidenceIds = new Set([...roles, ...relations, ...financials].flatMap(item => item.evidence_ids));
    return copy({ company: index.entities.get(companyId), roles, relations, financials, coverage: index.coverage.get(companyId) || [], evidence: [...evidenceIds].map(id => index.evidence.get(id)).filter(Boolean) });
  }
  function selectEvidence(index, ids) {
    return copy(ids.map(id => index.evidence.get(id)).filter(Boolean));
  }
  function completePeriod(period) {
    const match = typeof period === 'string' && /^(ROC)?(\d{3,4})-(\d{2})-(\d{2})~(?:ROC)?(\d{3,4})-(\d{2})-(\d{2})$/.exec(period);
    if (!match) return null;
    const offset = match[1] ? 1911 : 0;
    function dateAt(position) {
      const year = Number(match[position]) + offset, month = Number(match[position + 1]), day = Number(match[position + 2]);
      const date = new Date(0); date.setUTCFullYear(year, month - 1, day); date.setUTCHours(0, 0, 0, 0);
      return date.getUTCFullYear() === year && date.getUTCMonth() === month - 1 && date.getUTCDate() === day ? date.toISOString().slice(0, 10) : null;
    }
    const start = dateAt(2), end = dateAt(5);
    return start && end && start <= end ? `${start}~${end}` : null;
  }
  function compare(index, companyIds, metric, period, view = filter(index)) {
    const visible = new Set(view.companies.map(item => item.id));
    const ids = [...new Set(companyIds)].filter(id => visible.has(id));
    const selectedPeriod = completePeriod(period);
    const rows = ids.flatMap(id => index.observations.get(id) || []).filter(item => item.metric === metric && (!selectedPeriod || completePeriod(item.period) === selectedPeriod));
    const reasons = [];
    if (!metric || metric === 'unknown') reasons.push('metric: missing');
    if (!selectedPeriod) reasons.push('period: incomplete selection');
    if (!ids.length) reasons.push('rows: no companies selected');
    ids.forEach(id => { const count = rows.filter(item => item.company_id === id).length; if (count !== 1) reasons.push(`rows: ${id} has ${count} observations`); });
    ['period', 'basis', 'currency', 'unit', 'scope'].forEach(field => {
      const values = rows.map(item => field === 'period' ? completePeriod(item.period) : item[field]);
      if (values.some(value => value == null || ['', 'unknown', 'null'].includes(String(value).trim().toLowerCase()))) reasons.push(`${field}: missing or incomplete`);
      if (new Set(values).size > 1) reasons.push(`${field}: incompatible`);
    });
    if (rows.some(item => item.value == null)) reasons.push('value: missing');
    return copy({ comparable: !reasons.length, reasons, rows });
  }
  const api = { createIndex, filter, select, selectEvidence, compare, completePeriod };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;
  const index = createIndex(JSON.parse(document.getElementById('snapshot').textContent));
  const byId = id => document.getElementById(id);
  const state = { companyId: null, comparison: new Set() };
  // Source names, quotes and locators never become markup or executable links.
  function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = String(text);
    if (className) element.className = className;
    return element;
  }
  function button(text, action) { const element = node('button', text); element.type = 'button'; element.addEventListener('click', action); return element; }
  function showEvidence(ids) {
    const panel = byId('evidence'); panel.replaceChildren();
    const proofs = selectEvidence(index, ids);
    if (!proofs.length) panel.append(node('p', '無證據', 'empty'));
    proofs.forEach(proof => {
      const card = node('article', undefined, 'card');
      card.append(node('pre', proof.quote ?? '原文未知'), node('p', `文件：${proof.document ?? '未知'}`), node('p', `定位：${proof.locator == null ? '未知' : JSON.stringify(proof.locator)}`), node('p', `來源類型：${proof.source_type ?? '未知'}`), node('p', `期別：${proof.period ?? '未知'}；查核日期：${proof.checked_at ?? '未知'}`));
      panel.append(card);
    });
  }
  function sourceButton(record) { return button('來源', () => showEvidence(record.evidence_ids || [])); }
  function renderDetail(view) {
    const panel = byId('detail'); panel.replaceChildren();
    const detail = select(index, state.companyId, view);
    if (!detail) { panel.append(node('p', '請選取公司／無符合資料', 'empty')); return; }
    panel.append(node('h3', detail.company.name), button('公司證據', () => showEvidence(detail.evidence.map(item => item.id))));
    detail.roles.forEach(item => { const card = node('p', `${item.stage} · ${item.product ?? '產品未知'} · ${item.status}`); card.append(sourceButton(item)); panel.append(card); });
    detail.relations.forEach(item => {
      const source = index.entities.get(item.source_id), target = index.entities.get(item.target_id);
      const card = node('p', `${source?.name ?? item.source_id} → ${target?.name ?? item.target_id} · ${item.predicate} · ${item.direction} · ${item.product ?? '未知'} · ${item.period ?? '期別未知'} · ${item.status}`);
      card.append(button('關係證據', () => showEvidence(item.evidence_ids))); panel.append(card);
    });
    panel.append(node('h3', '財務與期別'));
    detail.financials.forEach(item => {
      const card = node('p', `${item.metric}：${item.value ?? '缺值'} ${item.currency ?? '幣別未知'} / ${item.unit} · ${item.period ?? '期別未知'} · ${item.basis ?? '口徑未知'} · ${item.scope}`);
      card.append(sourceButton(item)); panel.append(card);
    });
    detail.coverage.forEach(item => {
      const warnings = item.warnings.map(warning => {
        if (typeof warning === 'string') return warning;
        return [warning?.reason, warning?.error].filter(value => typeof value === 'string' && value).join(' / ') || '未知警告';
      });
      panel.append(node('p', `資料缺漏：${item.missing.join('、') || '無'}；警告：${warnings.join('、') || '無'}`));
    });
  }
  function renderComparison(view) {
    const panel = byId('comparison'); panel.replaceChildren();
    const result = compare(index, [...state.comparison], byId('metric').value, byId('period').value, view);
    if (!result.comparable) { panel.append(node('p', `無法比較：${result.reasons.join('；')}`, 'blocked')); return; }
    const table = node('table'); const header = node('tr');
    ['公司', '數值', '幣別／單位', '期別／口徑', '證據'].forEach(text => header.append(node('th', text))); table.append(header);
    result.rows.forEach(item => {
      const row = node('tr');
      [index.entities.get(item.company_id)?.name ?? item.company_id, item.value, `${item.currency} / ${item.unit}`, `${item.period} / ${item.basis} / ${item.scope}`].forEach(text => row.append(node('td', text)));
      const source = node('td'); source.append(sourceButton(item)); row.append(source); table.append(row);
    }); panel.append(table);
  }
  function update() {
    const view = filter(index, { search: byId('search').value, stage: byId('stage').value, includePending: byId('pending').checked });
    const visibleIds = new Set(view.companies.map(item => item.id));
    state.comparison = new Set([...state.comparison].filter(id => visibleIds.has(id)));
    if (!visibleIds.has(state.companyId)) state.companyId = null;
    byId('evidence').replaceChildren(node('p', '請選取來源', 'empty'));
    const overview = byId('overview'); overview.replaceChildren();
    if (!view.companies.length) overview.append(node('p', '無符合資料', 'empty'));
    const groups = new Map(stages.map(stage => [stage, []]));
    view.companies.forEach(company => {
      const companyStages = new Set(view.roles.filter(role => role.company_id === company.id).map(role => role.stage));
      if (!companyStages.size) companyStages.add('待分類');
      companyStages.forEach(stage => { if (!groups.has(stage)) groups.set(stage, []); groups.get(stage).push(company); });
    });
    groups.forEach((companies, stage) => {
      if (!companies.length) return;
      overview.append(node('h3', stage));
      companies.forEach(company => {
        const card = node('div', undefined, 'card');
        card.append(button(`${company.name} (${company.ticker ?? '未知'})`, () => { state.companyId = company.id; byId('evidence').replaceChildren(node('p', '請選取來源')); renderDetail(view); }));
        const label = node('label', '比較 '), checkbox = node('input'); checkbox.type = 'checkbox'; checkbox.checked = state.comparison.has(company.id);
        checkbox.addEventListener('change', () => { if (checkbox.checked) state.comparison.add(company.id); else state.comparison.delete(company.id); update(); });
        label.append(checkbox); card.append(label); overview.append(card);
      });
    }); renderDetail(view); renderComparison(view);
  }
  const stageOptions = new Set([...stages, ...index.snapshot.roles.map(item => item.stage)]);
  stageOptions.forEach(stage => { const option = node('option', stage); option.value = stage; byId('stage').append(option); });
  [...new Set(index.snapshot.observations.map(item => item.metric))].forEach(metric => { const option = node('option', metric); option.value = metric; byId('metric').append(option); });
  [...new Set(index.snapshot.observations.map(item => item.period).filter(completePeriod))].forEach(period => { const option = node('option', period); option.value = period; byId('period').append(option); });
  ['search', 'stage', 'pending', 'metric', 'period'].forEach(id => byId(id).addEventListener(id === 'search' ? 'input' : 'change', update));
  update();
}());
