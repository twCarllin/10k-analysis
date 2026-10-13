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
    const offset = match[1] || match[2].length === 3 ? 1911 : 0;
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
  const analysisMetrics = ['gross_margin', 'operating_margin', 'net_margin', 'fcf_margin'];
  const analysisAmounts = ['revenue', 'gross_profit', 'operating_income', 'net_income', 'cfo', 'capex'];
  const knownAnalysisField = value => value != null && !['', 'unknown', 'null'].includes(String(value).trim().toLowerCase());
  function analysisPeriods(index, companyIds) {
    const choices = new Map();
    [...new Set(companyIds)].forEach(id => (index.observations.get(id) || []).forEach(item => {
      const period = completePeriod(item.period);
      if (!period || !knownAnalysisField(item.basis) || !knownAnalysisField(item.scope)) return;
      if (![...analysisMetrics, ...analysisAmounts].includes(item.metric)) return;
      const choice = { period, basis: item.basis, scope: item.scope };
      choices.set(JSON.stringify(choice), choice);
    }));
    const sorted = [...choices.values()].sort((a, b) => b.period.split('~')[1].localeCompare(a.period.split('~')[1]) || b.period.localeCompare(a.period) || a.basis.localeCompare(b.basis) || a.scope.localeCompare(b.scope));
    const usable = sorted.filter(choice => companyIds.some(id => {
      const summary = financialSummary(index, id, choice.period, choice.basis, choice.scope);
      return analysisMetrics.some(metric => summary.cells[metric].value !== null);
    }));
    return usable.length ? usable : sorted;
  }
  function emptyAnalysisCell(reason) {
    return { value: null, reason, formula: null, inputs: null, evidenceIds: [], delta: null };
  }
  function analysisProofValid(index, item) {
    return Array.isArray(item.evidence_ids) && item.evidence_ids.length > 0 && item.evidence_ids.every(id => index.evidence.has(id));
  }
  function uniqueAnalysisObservation(index, rows) {
    if (!rows.length) return { reason: '缺資料' };
    if (rows.some(item => item.quality?.conflict || !Number.isFinite(item.value))) return { reason: '數值缺漏或衝突' };
    if (rows.some(item => !analysisProofValid(index, item))) return { reason: '來源缺漏' };
    const signatures = rows.map(item => JSON.stringify([item.value, item.unit, item.currency, item.formula, item.inputs]));
    if (new Set(signatures).size > 1) return { reason: '數值或口徑衝突' };
    return { item: { ...rows[0], evidence_ids: [...new Set(rows.flatMap(item => item.evidence_ids))] } };
  }
  function validDirectFcf(item) {
    const inputs = item.inputs;
    if (typeof item.formula !== 'string' || !inputs || !Number.isFinite(inputs.revenue) || inputs.revenue === 0) return false;
    const compact = item.formula.replace(/\s/g, '');
    const matchesValue = fcf => Math.abs(item.value - fcf / inputs.revenue * 100) < 1e-8;
    const hasRawInputs = Object.hasOwn(inputs, 'cfo') || Object.hasOwn(inputs, 'capex');
    const rawInputsValid = Number.isFinite(inputs.cfo) && Number.isFinite(inputs.capex);
    if (compact === 'fcf/revenue*100') {
      if (!Number.isFinite(inputs.fcf)) return false;
      if (!hasRawInputs) return matchesValue(inputs.fcf);
      if (!rawInputsValid) return false;
      const expectedFcf = inputs.cfo - Math.abs(inputs.capex);
      return Math.abs(inputs.fcf - expectedFcf) < 1e-8 && matchesValue(inputs.fcf);
    }
    if (!rawInputsValid) return false;
    const signedLedger = compact === '(cfo+capex)/revenue*100' && inputs.capex <= 0;
    const paymentAmount = compact === '(cfo-capex)/revenue*100' && inputs.capex >= 0;
    if (!signedLedger && !paymentAmount) return false;
    const expectedFcf = inputs.cfo + (signedLedger ? inputs.capex : -inputs.capex);
    if (Object.hasOwn(inputs, 'fcf') && (!Number.isFinite(inputs.fcf) || Math.abs(inputs.fcf - expectedFcf) >= 1e-8)) return false;
    return matchesValue(expectedFcf);
  }
  function analysisCapex(index, item) {
    const pointers = item.evidence_ids.map(id => index.evidence.get(id)?.locator?.pointer || '');
    const ledger = pointers.some(pointer => pointer.startsWith('/bundle/statements/rows/'));
    const xbrl = item.quality?.source === 'xbrl' && item.quality?.concept === 'PaymentsToAcquirePropertyPlantAndEquipment';
    if (ledger === xbrl) return null;
    if (ledger && item.value <= 0) return -item.value;
    if (xbrl && item.value >= 0) return item.value;
    return null;
  }
  function derivedAnalysisCell(index, rows, metric) {
    const numerator = { gross_margin: 'gross_profit', operating_margin: 'operating_income', net_margin: 'net_income' }[metric];
    const keys = numerator ? ['revenue', numerator] : ['revenue', 'cfo', 'capex'];
    const selected = keys.map(key => uniqueAnalysisObservation(index, rows.filter(item => item.metric === key && knownAnalysisField(item.unit) && knownAnalysisField(item.currency))));
    const blocked = selected.find(result => result.reason);
    if (blocked) return emptyAnalysisCell(blocked.reason);
    const amounts = selected.map(result => result.item);
    const revenue = amounts[0];
    const compatible = amounts.every(item => knownAnalysisField(item.unit) && item.unit !== '%' && knownAnalysisField(item.currency) && item.unit === revenue.unit && item.currency === revenue.currency);
    if (!compatible) return emptyAnalysisCell('金額單位或幣別不相容');
    if (revenue.value === 0) return emptyAnalysisCell('營收為零');
    const inputs = Object.fromEntries(amounts.map(item => [item.metric, item.value]));
    let amount = numerator ? inputs[numerator] : null;
    if (!numerator) {
      inputs.capex_outflow = analysisCapex(index, amounts[2]);
      if (inputs.capex_outflow === null) return emptyAnalysisCell('資本支出來源或符號不明');
      amount = inputs.cfo - inputs.capex_outflow;
    }
    const value = amount / revenue.value * 100;
    if (!Number.isFinite(value)) return emptyAnalysisCell('數值非有限值');
    return { value, reason: null, formula: numerator ? `${numerator} / revenue * 100` : '(cfo - capex_outflow) / revenue * 100', inputs, evidenceIds: [...new Set(amounts.flatMap(item => item.evidence_ids))], delta: null };
  }
  function analysisCell(index, rows, metric) {
    const directRows = rows.filter(item => item.metric === metric && item.unit === '%');
    if (!directRows.length) return derivedAnalysisCell(index, rows, metric);
    const result = uniqueAnalysisObservation(index, directRows);
    if (result.reason) return emptyAnalysisCell(result.reason);
    const item = result.item;
    if (metric === 'fcf_margin' && !validDirectFcf(item)) return emptyAnalysisCell('自由現金流公式或輸入不完整');
    return { value: item.value, reason: null, formula: item.formula, inputs: copy(item.inputs), evidenceIds: item.evidence_ids, delta: null };
  }
  function previousAnalysisPeriod(period) {
    if (!period) return null;
    const previous = period.split('~').map(date => `${String(Number(date.slice(0, 4)) - 1).padStart(4, '0')}${date.slice(4)}`).join('~');
    return completePeriod(previous);
  }
  function financialSummary(index, companyId, period, basis, scope) {
    const selectedPeriod = completePeriod(period);
    const company = index.entities.get(companyId) || null;
    const rows = index.observations.get(companyId) || [];
    const selectionValid = selectedPeriod && knownAnalysisField(basis) && knownAnalysisField(scope);
    const atPeriod = target => rows.filter(item => completePeriod(item.period) === target && item.basis === basis && item.scope === scope);
    const cells = {};
    analysisMetrics.forEach(metric => {
      const missingReason = !company || !rows.length ? '未匯入' : '期別或口徑不完整';
      const cell = selectionValid && company && rows.length ? analysisCell(index, atPeriod(selectedPeriod), metric) : emptyAnalysisCell(missingReason);
      const priorPeriod = previousAnalysisPeriod(selectedPeriod);
      if (cell.value !== null && priorPeriod) {
        const prior = analysisCell(index, atPeriod(priorPeriod), metric);
        if (prior.value !== null) {
          cell.delta = cell.value - prior.value;
          cell.currentPeriod = selectedPeriod;
          cell.priorPeriod = priorPeriod;
          cell.priorEvidenceIds = prior.evidenceIds;
        }
      }
      cells[metric] = cell;
    });
    return { companyId, company, period: selectedPeriod, basis, scope, cells, deltaUnit: '百分點' };
  }
  function analysisComparison(index, companyIds, options = {}) {
    const ids = [...new Set(companyIds)];
    const periods = analysisPeriods(index, ids);
    const selection = options.period === undefined ? (periods[0] || { period: null, basis: null, scope: null }) : { period: options.period, basis: options.basis, scope: options.scope };
    return { ...selection, periods, rows: ids.map(id => financialSummary(index, id, selection.period, selection.basis, selection.scope)) };
  }
  function periodDays(period) {
    const [start, end] = period.split('~');
    return (Date.parse(end) - Date.parse(start)) / 86400000 + 1;
  }
  function financialTrend(index, companyId, metric, selection = {}) {
    const period = completePeriod(selection.period);
    if (!period || !analysisMetrics.includes(metric) || !knownAnalysisField(selection.basis) || !knownAnalysisField(selection.scope)) return { points: [], reason: '期別或口徑不完整' };
    const cutoff = period.split('~')[1];
    const periods = [...new Set((index.observations.get(companyId) || []).filter(item => item.basis === selection.basis && item.scope === selection.scope && [...analysisMetrics, ...analysisAmounts].includes(item.metric)).map(item => completePeriod(item.period)).filter(candidate => candidate && candidate.split('~')[1] <= cutoff && Math.abs(periodDays(candidate) - periodDays(period)) <= 7))].sort().slice(-8);
    const points = periods.map(candidate => {
      const cell = financialSummary(index, companyId, candidate, selection.basis, selection.scope).cells[metric];
      const evidenceIds = cell.value !== null ? cell.evidenceIds : [...new Set((index.observations.get(companyId) || []).filter(item => completePeriod(item.period) === candidate && item.basis === selection.basis && item.scope === selection.scope && (item.metric === metric || analysisAmounts.includes(item.metric))).flatMap(item => item.evidence_ids || []))];
      return { period: candidate, value: cell.value, reason: cell.reason, formula: cell.formula, inputs: cell.inputs, evidenceIds };
    });
    const validCount = points.filter(point => point.value !== null).length;
    const reason = points.length === 0 ? '未匯入可比期間' : validCount === 0 ? '無有效比率，無法判讀趨勢' : points.length === 1 ? '僅一個期別，無法判讀趨勢' : validCount === 1 ? '僅一個有效值，無法判讀趨勢' : null;
    return { points, validCount, reason };
  }
  function relationStrength(index, edge, requestedKind) {
    if (requestedKind === undefined) {
      const sales = relationStrength(index, edge, 'sales_share');
      const purchase = relationStrength(index, edge, 'purchase_share');
      if (sales.value !== null) return sales;
      if (purchase.value !== null) return purchase;
      return sales.kind ? sales : purchase;
    }
    const shares = (edge.disclosures || []).filter(item => ['sales_share', 'purchase_share'].includes(item.kind));
    const kind = shares.some(item => item.kind === requestedKind) ? requestedKind : null;
    const denominator = kind === 'sales_share' ? '披露供應商同期總銷貨／營收' : kind === 'purchase_share' ? '披露買方同期總進貨' : null;
    const missing = (reason, period = null) => ({ value: null, kind, period, denominator, evidenceIds: [], reason, width: 2 });
    if (!kind) return missing('占比未揭露，未知不是零');
    const selected = shares.filter(item => item.kind === kind);
    if (selected.some(item => !completePeriod(item.period))) return missing('占比期別不完整');
    const period = selected.map(item => completePeriod(item.period)).sort().at(-1);
    const latest = selected.filter(item => completePeriod(item.period) === period);
    const valid = latest.every(item => Number.isFinite(item.value) && item.value >= 0 && item.value <= 100 && item.unit === '%' && item.currency == null && analysisProofValid(index, item));
    if (!valid) return missing('最新占比資料或來源不完整', period);
    if (new Set(latest.map(item => item.value)).size !== 1) return missing('最新占比揭露衝突', period);
    const value = latest[0].value;
    return { value, kind, period, denominator, evidenceIds: [...new Set(latest.flatMap(item => item.evidence_ids))], reason: null, width: 2 + 6 * Math.sqrt(value / 100) };
  }
  function researchSignal(summary, metrics, text, followup = null) {
    const current = metrics.map(metric => ({ metric, period: summary.period, ...summary.cells[metric] }));
    const prior = metrics.filter(metric => summary.cells[metric].delta !== null).map(metric => {
      const cell = summary.cells[metric];
      return { metric, period: cell.priorPeriod, value: cell.value - cell.delta, evidenceIds: cell.priorEvidenceIds || [] };
    });
    return { company: summary.company, companyId: summary.companyId, period: summary.period, metrics, text, followup, current, prior, evidenceIds: [...new Set([...current, ...prior].flatMap(item => item.evidenceIds))] };
  }
  function researchSignals(index, companyId, selection = {}) {
    const summary = financialSummary(index, companyId, selection.period, selection.basis, selection.scope);
    const cells = summary.cells, signals = [];
    const hasDelta = metric => cells[metric].value !== null && Number.isFinite(cells[metric].delta);
    if (hasDelta('gross_margin') && hasDelta('operating_margin') && cells.gross_margin.delta < 0 && cells.operating_margin.delta > 0) {
      signals.push(researchSignal(summary, ['gross_margin', 'operating_margin'], `毛利率同比下降 ${Math.abs(cells.gross_margin.delta).toFixed(2)} 百分點、營業利益率同比上升 ${cells.operating_margin.delta.toFixed(2)} 百分點；可追查費用率或業務組合`, '可追查費用率或業務組合'));
    }
    if (hasDelta('net_margin') && hasDelta('fcf_margin') && cells.net_margin.delta > 0 && Math.abs(cells.fcf_margin.delta) < 0.1 - 1e-10) {
      const signal = researchSignal(summary, ['net_margin', 'fcf_margin'], `稅後淨利率同比上升 ${cells.net_margin.delta.toFixed(2)} 百分點、自由現金流營收率大致持平（同比變動絕對值小於 0.1 百分點）；可追查營運資金與資本支出`, '可追查營運資金與資本支出');
      signal.threshold = { metric: 'fcf_margin', absoluteDeltaBelow: 0.1, unit: '百分點' };
      signals.push(signal);
    }
    const edges = index.relations.get(companyId) || [];
    for (const edge of edges) {
      if (signals.length >= 3) break;
      const ownerKind = edge.source_id === companyId ? 'sales_share' : edge.target_id === companyId ? 'purchase_share' : null;
      if (!ownerKind) continue;
      const strength = relationStrength(index, edge, ownerKind);
      if (strength.value === null || strength.period !== summary.period) continue;
      signals.push({ company: summary.company, companyId, period: strength.period, metrics: [strength.kind], text: `${strength.kind === 'sales_share' ? '銷貨／營收占比' : '進貨占比'} ${strength.value}%（${strength.period}；分母：${strength.denominator}）`, followup: null, evidenceIds: strength.evidenceIds, current: [strength], prior: [], relationId: edge.id });
    }
    const covered = new Set(signals.flatMap(signal => signal.metrics));
    const labels = { gross_margin: '毛利率', operating_margin: '營業利益率', net_margin: '稅後淨利率', fcf_margin: '自由現金流營收率' };
    for (const metric of analysisMetrics) {
      if (signals.length >= 3) break;
      const cell = cells[metric];
      if (cell.value === null || covered.has(metric)) continue;
      const change = hasDelta(metric) ? `；同比${cell.delta > 0 ? '上升' : cell.delta < 0 ? '下降' : '持平'} ${Math.abs(cell.delta).toFixed(2)} 百分點` : '';
      signals.push(researchSignal(summary, [metric], `${labels[metric]} ${cell.value.toFixed(2)}%${change}`));
    }
    if (!signals.length) signals.push({ company: summary.company, companyId, period: summary.period, metrics: [], text: '缺少可核對資料，請補財務或占比來源', followup: '補資料', evidenceIds: [], current: [], prior: [] });
    return signals;
  }
  // Graph IDs occupy a client-only namespace; entity identity remains unchanged.
  const graphId = (kind, value) => `map:${kind}:${JSON.stringify(value)}`;
  function createGraph(index) {
    const nodes = new Map([['map:root', { id: 'map:root', kind: 'root', name: '產業地圖' }]]);
    const edges = new Map();
    const addNode = item => { if (!nodes.has(item.id)) nodes.set(item.id, copy(item)); };
    const addEdge = item => edges.set(item.id, copy(item));
    const navigation = (id, name) => {
      addNode({ id, kind: 'industry', name });
      addEdge({ id: graphId('navigation', id), source_id: 'map:root', target_id: id, kind: 'navigation', evidence_ids: [] });
    };
    index.snapshot.entities.forEach(addNode);
    index.snapshot.roles.forEach(role => {
      const industryId = graphId('industry', role.theme);
      navigation(industryId, role.theme);
      addEdge({ ...role, id: graphId('classification', role.id), source_id: industryId, target_id: role.company_id, kind: 'classification' });
      if (role.product) {
        const productId = graphId('product', role.product);
        addNode({ id: productId, kind: 'product', name: role.product });
        addEdge({ ...role, id: graphId('offering', role.id), source_id: role.company_id, target_id: productId, kind: 'offering' });
      }
    });
    index.snapshot.coverage.forEach(record => {
      if (index.roles.has(record.company_id)) return;
      const industryId = 'map:unclassified';
      navigation(industryId, '待分類');
      addEdge({ ...record, id: graphId('coverage', record.id), source_id: industryId, target_id: record.company_id, kind: 'classification', evidence_ids: [] });
    });
    index.snapshot.relations.forEach(record => addEdge({ ...record, kind: 'relation' }));
    return { nodes: [...nodes.values()], edges: [...edges.values()] };
  }
  function createGraphState() {
    return { roots: ['map:root'], expanded: ['map:root'], focus: null };
  }
  function expandGraph(state, id) {
    return copy({ ...state, expanded: [...new Set([...state.expanded, id])] });
  }
  function collapseGraph(state, id) {
    return copy({ ...state, expanded: state.expanded.filter(value => value !== id) });
  }
  function resetGraph() { return createGraphState(); }
  function focusGraph(graph, state, id) {
    if (!graph.nodes.some(node => node.id === id)) return copy(state);
    return copy({ ...state, roots: [...new Set([...state.roots, id])], focus: id });
  }
  function searchGraph(graph, query) {
    const term = String(query || '').trim().toLocaleLowerCase();
    if (!term) return [];
    return copy(graph.nodes.filter(node => [node.name, node.ticker, ...(node.aliases || [])].some(value => String(value || '').toLocaleLowerCase().includes(term))));
  }
  // Both graph and detail consume this direction predicate for the selected company.
  function graphRelations(graph, companyId, options = {}) {
    return copy(graph.edges.filter(edge => {
      if (edge.kind !== 'relation' || (edge.source_id !== companyId && edge.target_id !== companyId)) return false;
      if (options.includePending === false && edge.status === 'pending') return false;
      if (options.direction === 'upstream') return edge.predicate === 'supplies_to' && edge.target_id === companyId;
      if (options.direction === 'downstream') return edge.predicate === 'supplies_to' && edge.source_id === companyId;
      if (options.direction === 'competitor') return edge.predicate === 'competes_with';
      return true;
    }).map(edge => ({ ...edge, direction: edge.source_id === companyId ? 'outgoing' : 'incoming' })));
  }
  function visibleGraph(graph, state, options = {}) {
    const expanded = new Set(state.expanded);
    const selectedId = options.companyId || state.focus;
    const directional = ['upstream', 'downstream', 'competitor'].includes(options.direction);
    const relations = graphRelations(graph, selectedId, options);
    const allowedRelations = new Set(relations.map(edge => edge.id));
    const allowedCompanies = new Set(selectedId ? [selectedId] : []);
    relations.forEach(edge => { allowedCompanies.add(edge.source_id); allowedCompanies.add(edge.target_id); });
    const nodeById = new Map(graph.nodes.map(node => [node.id, node]));
    const ids = new Set(state.roots.filter(id => {
      const node = nodeById.get(id);
      return node && (!directional || node.kind !== 'company' || allowedCompanies.has(id));
    }));
    const edges = new Map();
    const queue = [...ids];
    const include = edge => {
      if (options.includePending === false && edge.status === 'pending') return false;
      if (!directional) return true;
      if (edge.kind === 'relation') return allowedRelations.has(edge.id);
      // Navigation may not reintroduce companies excluded by relation filters.
      if (edge.kind === 'classification') return allowedCompanies.has(edge.target_id);
      if (edge.kind === 'offering') return allowedCompanies.has(edge.source_id);
      return true;
    };
    while (queue.length) {
      const id = queue.shift();
      if (!expanded.has(id)) continue;
      graph.edges.forEach(edge => {
        const outgoing = edge.source_id === id;
        const incoming = edge.target_id === id && ['relation', 'offering'].includes(edge.kind);
        if ((!outgoing && !incoming) || !include(edge)) return;
        const otherId = outgoing ? edge.target_id : edge.source_id;
        if (!nodeById.has(otherId)) return;
        edges.set(edge.id, edge);
        if (!ids.has(otherId)) { ids.add(otherId); queue.push(otherId); }
      });
    }
    return copy({ nodes: graph.nodes.filter(node => ids.has(node.id)), edges: [...edges.values()] });
  }
  function graphDetail(index, graph, view, id) {
    const item = view.nodes.find(node => node.id === id) || view.edges.find(edge => edge.id === id);
    if (!item) return null;
    const isEdge = 'source_id' in item;
    const records = isEdge ? [item] : view.edges.filter(edge => edge.source_id === id || edge.target_id === id);
    const relations = records.filter(edge => edge.kind === 'relation');
    const neighbors = records.filter(edge => !isEdge && edge.kind !== 'relation').map(edge => ({
      edge, node: view.nodes.find(node => node.id === (edge.source_id === id ? edge.target_id : edge.source_id))
    })).filter(entry => entry.node);
    const financials = !isEdge && item.kind === 'company' ? index.observations.get(id) || [] : [];
    const evidenceIds = [...new Set([...records, ...financials].flatMap(record => record.evidence_ids || []))];
    return copy({ item, isEdge, records, relations, neighbors, financials,
      evidenceIds, evidence: selectEvidence(index, evidenceIds),
      coverage: !isEdge ? index.coverage.get(id) || [] : [],
      owner: item.owner_id ? index.entities.get(item.owner_id) || { id: item.owner_id, name: '未知公司' } : null,
      counts: {
        upstream: relations.filter(edge => edge.predicate === 'supplies_to' && edge.target_id === id).length,
        downstream: relations.filter(edge => edge.predicate === 'supplies_to' && edge.source_id === id).length,
        competitor: relations.filter(edge => edge.predicate === 'competes_with').length
      }
    });
  }
  // Persistent positions are independent of graph visibility and viewport changes.
  function layoutGraph(view, previous = {}, anchorId = 'map:root') {
    const positions = Object.fromEntries(Object.entries(previous).map(([id, point]) => [id, { ...point }]));
    const anchor = positions[anchorId] || { x: 0, y: 0 };
    if (!positions['map:root']) positions['map:root'] = { x: 0, y: 0 };
    const newcomers = view.nodes.filter(item => !positions[item.id]);
    newcomers.forEach((item, number) => {
      const ring = Math.floor(number / 8), slot = number % 8;
      const angle = slot * Math.PI / 4 + ring * .27;
      const radius = 250 + ring * 210;
      let point = { x: anchor.x + Math.cos(angle) * radius, y: anchor.y + Math.sin(angle) * radius };
      // Avoid prior cards without relocating them, including previously hidden cards.
      while (Object.values(positions).some(other => Math.abs(other.x - point.x) < 190 && Math.abs(other.y - point.y) < 85)) {
        point = { x: point.x + Math.cos(angle) * 210, y: point.y + Math.sin(angle) * 210 };
      }
      positions[item.id] = point;
    });
    return positions;
  }
  // A focused view never traverses a neighbor's relationships.
  function centeredGraph(graph, centerId = 'map:root', options = {}) {
    const center = graph.nodes.find(node => node.id === centerId);
    if (!center) return { nodes: [], edges: [] };
    const allowed = new Set(graphRelations(graph, centerId, options).map(edge => edge.id));
    const edges = options.collapsed ? [] : graph.edges.filter(edge => {
      if (edge.source_id !== centerId && edge.target_id !== centerId) return false;
      if (options.includePending === false && edge.status === 'pending') return false;
      return edge.kind !== 'relation' || allowed.has(edge.id);
    });
    const ids = new Set([centerId, ...edges.flatMap(edge => [edge.source_id, edge.target_id])]);
    const nodes = graph.nodes.filter(node => ids.has(node.id));
    const present = new Set(nodes.map(node => node.id));
    return copy({ nodes, edges: edges.filter(edge => present.has(edge.source_id) && present.has(edge.target_id)) });
  }
  function neighborZone(view, centerId, id) {
    const edges = view.edges.filter(edge => [edge.source_id, edge.target_id].includes(id));
    // Fixed priority assigns one card; every original edge stays available.
    if (edges.some(edge => edge.predicate === 'supplies_to' && edge.target_id === centerId)) return 'upstream';
    if (edges.some(edge => edge.predicate === 'supplies_to' && edge.source_id === centerId)) return 'downstream';
    if (edges.some(edge => edge.predicate === 'competes_with')) return 'competitor';
    if (edges.some(edge => edge.kind === 'offering')) return 'product';
    return 'classification';
  }
  function pagedCenteredGraph(graph, centerId, options = {}) {
    const full = centeredGraph(graph, centerId, options);
    const counts = {}, remaining = {}, shown = new Set([centerId]);
    full.nodes.filter(node => node.id !== centerId).forEach(node => {
      const zone = neighborZone(full, centerId, node.id);
      counts[zone] = (counts[zone] || 0) + 1;
      if (counts[zone] <= (options.limits?.[zone] || 5)) shown.add(node.id);
      else remaining[zone] = (remaining[zone] || 0) + 1;
    });
    return { nodes: full.nodes.filter(node => shown.has(node.id)),
      edges: full.edges.filter(edge => shown.has(edge.source_id) && shown.has(edge.target_id)), remaining };
  }
  function centeredLayout(view, centerId) {
    const positions = { [centerId]: { x: 0, y: 0 } };
    const groups = { upstream: [], downstream: [], competitor: [], product: [], classification: [] };
    view.nodes.filter(node => node.id !== centerId).forEach(node => groups[neighborZone(view, centerId, node.id)].push(node));
    const productExtent = Math.max(0, groups.product.length - 1) * 105;
    const classificationExtent = groups.product.length && groups.classification.length
      ? (groups.product.length + 2 * groups.classification.length - 1) * 105 + 115
      : Math.max(0, groups.classification.length - 1) * 105;
    const sideX = Math.max(330, productExtent + 220, classificationExtent + 220, (groups.competitor.length - 1) * 105 + 220);
    const sideHeight = (Math.max(groups.upstream.length, groups.downstream.length) - 1) * 50;
    const lowerY = Math.max(220, sideHeight + 120);
    Object.entries(groups).forEach(([zone, nodes]) => nodes.forEach((node, number) => {
      if (zone === 'upstream' || zone === 'downstream') {
        positions[node.id] = { x: (zone === 'upstream' ? -1 : 1) * sideX, y: (number - (nodes.length - 1) / 2) * 100 };
      } else {
        const y = zone === 'competitor' ? lowerY : -220;
        const offset = zone === 'classification' && groups.product.length ? -(groups.product.length + nodes.length) * 105 - 115 : 0;
        positions[node.id] = { x: offset + (number - (nodes.length - 1) / 2) * 210, y };
      }
    }));
    return positions;
  }
  function fitCenteredGraph(view, positions, width = 1000, height = 650) {
    const points = view.nodes.map(node => positions[node.id]);
    const halfWidth = Math.max(115, ...points.map(point => Math.abs(point.x) + 115));
    const halfHeight = Math.max(95, ...points.map(point => Math.abs(point.y) + 95));
    // Keep labels readable; large expanded sections can be reached by panning.
    const scale = Math.max(.75, Math.min(1, width / (2 * halfWidth) * .9, height / (2 * halfHeight) * .9));
    return { x: width / 2, y: height / 2, scale };
  }
  function edgeGeometry(source, target) {
    const dx = target.x - source.x, dy = target.y - source.y;
    if (!dx && !dy) return `M ${source.x} ${source.y - 36} C ${source.x + 150} ${source.y - 150} ${source.x + 150} ${source.y + 150} ${source.x} ${source.y + 36}`;
    const boundary = Math.min(dx ? 90 / Math.abs(dx) : Infinity, dy ? 36 / Math.abs(dy) : Infinity, .45);
    const endBoundary = Math.min(dx ? 98 / Math.abs(dx) : Infinity, dy ? 44 / Math.abs(dy) : Infinity, .45);
    return `M ${source.x + dx * boundary} ${source.y + dy * boundary} L ${target.x - dx * endBoundary} ${target.y - dy * endBoundary}`;
  }
  function fitGraph(view, positions, width = 1000, height = 650) {
    if (!view.nodes.length) return { x: width / 2, y: height / 2, scale: 1 };
    const points = view.nodes.map(item => positions[item.id]);
    const left = Math.min(...points.map(point => point.x)) - 115;
    const right = Math.max(...points.map(point => point.x)) + 115;
    const top = Math.min(...points.map(point => point.y)) - 65;
    const bottom = Math.max(...points.map(point => point.y)) + 65;
    const scale = Math.max(.15, Math.min(2.5, width / (right - left) * .9, height / (bottom - top) * .9));
    return { x: width / 2 - (left + right) / 2 * scale, y: height / 2 - (top + bottom) / 2 * scale, scale };
  }
  function zoomGraph(camera, factor, point = { x: 500, y: 325 }) {
    const scale = Math.max(.15, Math.min(2.5, camera.scale * factor));
    const ratio = scale / camera.scale;
    return { x: point.x - (point.x - camera.x) * ratio, y: point.y - (point.y - camera.y) * ratio, scale };
  }
  function startGraphUI(index) {
    const byId = id => document.getElementById(id);
    const viewTabs = [byId('graph-tab'), byId('table-tab')];
    function selectViewTab(selected) {
      viewTabs.forEach(tab => {
        const active = tab === selected;
        tab.setAttribute('aria-selected', String(active));
        tab.tabIndex = active ? 0 : -1;
        byId(tab.getAttribute('aria-controls')).hidden = !active;
      });
    }
    viewTabs.forEach((tab, position) => {
      tab.addEventListener('click', () => selectViewTab(tab));
      tab.addEventListener('keydown', event => {
        let next;
        if (event.key === 'ArrowRight' || event.key === 'ArrowLeft') next = viewTabs[1 - position];
        if (event.key === 'Home') next = viewTabs[0];
        if (event.key === 'End') next = viewTabs[viewTabs.length - 1];
        if (!next) return;
        event.preventDefault(); selectViewTab(next); next.focus();
      });
    });
    const svg = byId('map'), graph = createGraph(index);
    const namespace = 'http://www.w3.org/2000/svg';
    const makeSVG = (tag, attributes = {}, text) => {
      const element = document.createElementNS(namespace, tag);
      Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, String(value)));
      if (text !== undefined) element.textContent = String(text);
      return element;
    };
    const html = (tag, text) => {
      const element = document.createElement(tag);
      if (text !== undefined) element.textContent = String(text);
      return element;
    };
    const defs = makeSVG('defs'), marker = makeSVG('marker', { id: 'supply-arrow', viewBox: '0 0 10 10', refX: 9, refY: 5, markerWidth: 9, markerHeight: 9, orient: 'auto', markerUnits: 'userSpaceOnUse' });
    marker.append(makeSVG('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: '#a4bdd5' }));
    defs.append(marker);
    const world = makeSVG('g'), zonesLayer = makeSVG('g'), edgesLayer = makeSVG('g'), nodesLayer = makeSVG('g');
    world.append(zonesLayer, edgesLayer, nodesLayer); svg.append(defs, world);
    let centerId = 'map:root', history = ['map:root'], collapsed = false, limits = {}, positions = {}, selectedId = 'map:root', selectedEdgeId = null;
    let camera = { x: 500, y: 325, scale: 1 }, visible, gesture = null, suppressClick = false;
    const kinds = { root: '起點', industry: '產業', company: '公司', product: '產品／服務' };
    function applyCamera() {
      world.setAttribute('transform', `translate(${camera.x} ${camera.y}) scale(${camera.scale})`);
      byId('zoom-level').textContent = `${Math.round(camera.scale * 100)}%`;
    }
    function localPoint(event) {
      // Convert through the SVG matrix, including preserveAspectRatio letterboxing.
      const point = svg.createSVGPoint(); point.x = event.clientX; point.y = event.clientY;
      return point.matrixTransform(svg.getScreenCTM().inverse());
    }
    const comparisonIds = new Set();
    const statusText = value => ({ pending: '待查核', confirmed: '已確認', terminated: '已終止' }[value] || '狀態未知');
    const relationText = edge => ({ supplies_to: '供貨', competes_with: '競爭' }[edge.predicate] || ({ classification: '分類', offering: '提供產品／服務', navigation: '產業導航' }[edge.kind] || '關係未知'));
    const readable = value => value == null || value === '' || value === 'unknown' ? '未知' : typeof value === 'object' ? JSON.stringify(value) : String(value);
    function actionButton(label, action) {
      const button = html('button', label); button.type = 'button'; button.addEventListener('click', action); return button;
    }
    function showGraphEvidence(ids) {
      byId('details-panel').open = true;
      const panel = byId('evidence'); panel.replaceChildren();
      const proofs = selectEvidence(index, ids);
      if (!proofs.length) panel.append(html('p', '無證據／待查核'));
      if (proofs.length < new Set(ids).size) panel.append(html('p', '部分證據缺失／待查核'));
      proofs.forEach(proof => {
        const card = html('article'); card.className = 'card';
        card.append(html('pre', proof.quote ?? '原文未知'), html('p', `文件：${readable(proof.document)}`),
          html('p', `定位：${readable(proof.locator)}`), html('p', `來源類型：${readable(proof.source_type)}`),
          html('p', `期別：${readable(proof.period)}；查核日期：${readable(proof.checked_at)}`));
        panel.append(card);
      });
    }
    function evidenceButton(record) {
      return actionButton('查看來源', () => showGraphEvidence(record.evidence_ids || []));
    }
    let analysisGroup = '', analysisSelection = null;
    const ratioLabels = { gross_margin: '毛利率', operating_margin: '營業利益率', net_margin: '稅後淨利率', fcf_margin: '自由現金流／營收' };
    function analysisCompanyIds() {
      const companies = visible.nodes.filter(node => node.kind === 'company').map(node => node.id);
      if (index.entities.has(centerId)) {
        const downstream = visible.edges.filter(edge => edge.predicate === 'supplies_to' && edge.source_id === centerId).map(edge => edge.target_id);
        const peers = visible.edges.filter(edge => edge.predicate === 'competes_with' && [edge.source_id, edge.target_id].includes(centerId)).map(edge => edge.source_id === centerId ? edge.target_id : edge.source_id);
        return [...new Set([centerId, ...(downstream.length ? downstream : peers)])].filter(id => companies.includes(id));
      }
      return companies;
    }
    function showRatioSource(cell, row) {
      showGraphEvidence([...new Set([...cell.evidenceIds, ...(cell.priorEvidenceIds || [])])]);
      const panel = byId('evidence');
      panel.append(html('p', `數值：${cell.value == null ? '缺資料' : `${cell.value}%`}`));
      if (cell.reason) panel.append(html('p', `缺資料：${cell.reason}`));
      panel.prepend(html('p', `公式：${readable(cell.formula)}；輸入：${readable(cell.inputs)}`),
        html('p', `當期：${row.period || '未知'}；去年：${cell.priorPeriod || '未匯入'}；同比：${cell.delta == null ? '—' : `${cell.delta.toFixed(2)} 百分點`}`));
      panel.tabIndex = -1; panel.focus({ preventScroll: true });
      panel.scrollIntoView({ block: 'nearest' });
    }
    let researchCompanyId = null, currentAnalysis = null;
    function appendTrend(td, row, metric) {
      const trend = financialTrend(index, row.companyId, metric, row);
      const periods = trend.points, label = html('small');
      const h1 = periods.length && periods.every(point => point.period.endsWith('-06-30') && point.period.includes('-01-01~'));
      label.className = 'trend-summary'; label.title = trend.reason || '';
      const shortReason = !periods.length ? '無歷史' : periods.length === 1 ? '僅1期；無法判趨勢' : trend.validCount < 2 ? '有效值不足；無法判趨勢' : '';
      label.textContent = `${periods.length}期${h1 ? ' H1' : ''}${shortReason ? `；${shortReason}` : ''}`;
      td.append(label);
      if (!periods.length) return;
      const chart = makeSVG('svg', { viewBox: '0 0 120 36', class: 'sparkline', role: 'group', 'aria-label': `${row.company?.name} ${ratioLabels[metric]}歷史` });
      const values = periods.filter(point => point.value !== null).map(point => point.value);
      const minimum = Math.min(...values), maximum = Math.max(...values), span = maximum - minimum || 1;
      const points = periods.map((point, number) => ({ x: periods.length === 1 ? 60 : 8 + number * 104 / (periods.length - 1), y: point.value === null ? 30 : 28 - (point.value - minimum) / span * 20 }));
      periods.forEach((point, number) => {
        const position = points[number];
        if (number && point.value !== null && periods[number - 1].value !== null) {
          const previous = points[number - 1];
          chart.append(makeSVG('path', { d: `M ${previous.x} ${previous.y} L ${position.x} ${position.y}`, class: 'trend-segment' }));
        }
        const dot = makeSVG('circle', { cx: position.x, cy: position.y, r: 4, tabindex: 0, role: 'button', class: `trend-point${point.value === null ? ' missing' : ''}`, 'data-period': point.period, 'aria-label': `${point.period} ${point.value === null ? `缺資料：${point.reason}` : `${point.value.toFixed(2)}%`} 查看來源` });
        dot.append(makeSVG('title', {}, `${point.period}；${point.value === null ? point.reason : `${point.value}%`}`));
        bindActivation(dot, () => showRatioSource(point, { period: point.period }));
        chart.append(dot);
      });
      td.append(chart);
    }
    function showSignalSource(signal) {
      showGraphEvidence(signal.evidenceIds || []);
      const panel = byId('evidence');
      const raw = html('details');
      raw.append(html('summary', '查看原始資料與定位'), ...panel.childNodes);
      panel.append(raw);
      const comparison = html('section');
      const labels = { ...ratioLabels, sales_share: '銷貨／營收占比', purchase_share: '進貨占比' };
      for (const [title, records] of [['當期', signal.current], ['去年', signal.prior]]) {
        comparison.append(html('h3', `${title}：`));
        if (!records?.length) comparison.append(html('p', '無可核對資料'));
        (records || []).forEach(record => {
          const value = Number.isFinite(record.value) ? `${record.value.toFixed(2)}%` : '缺資料';
          comparison.append(html('p', `${labels[record.metric || record.kind] || '指標'}：${value}；期間：${record.period || '未知'}`));
          if (record.denominator) comparison.append(html('p', `分母：${record.denominator}`));
          if (record.reason) comparison.append(html('p', `缺資料原因：${record.reason}`));
        });
      }
      panel.prepend(html('p', `${signal.company?.name || signal.companyId}；${signal.period}；${signal.text}`),
        html('p', '這是已匯入資料的事實與可追查事項，不代表因果、預測或投資排序。'),
        comparison);
      if (signal.threshold) panel.prepend(html('p', `持平門檻：同比變動絕對值小於 ${signal.threshold.absoluteDeltaBelow} ${signal.threshold.unit}`));
      panel.tabIndex = -1; panel.focus({ preventScroll: true }); panel.scrollIntoView({ block: 'nearest' });
    }
    let traceEdgeId = null;
    function traceAmount(companyId, metric, selection) {
      const rows = (index.observations.get(companyId) || []).filter(item => item.metric === metric && completePeriod(item.period) === selection.period && item.basis === selection.basis && item.scope === selection.scope && knownAnalysisField(item.unit) && item.unit !== '%' && knownAnalysisField(item.currency));
      const result = uniqueAnalysisObservation(index, rows);
      if (result.reason) return { reason: result.reason };
      if (metric === 'capex' && analysisCapex(index, result.item) === null) return { reason: '資本支出來源或符號不明' };
      return { item: result.item };
    }
    function renderTrace(selection = currentAnalysis?.selection || {}) {
      const panel = byId('supply-trace'); panel.replaceChildren();
      const edge = visible.edges.find(item => item.id === traceEdgeId && item.predicate === 'supplies_to');
      panel.hidden = !edge;
      if (!edge) { traceEdgeId = null; return; }
      const supplier = index.entities.get(edge.source_id), buyer = index.entities.get(edge.target_id);
      panel.append(html('h2', `供應關係追查：${supplier?.name || edge.source_id} → ${buyer?.name || edge.target_id}`), html('p', `財務期別：${selection.period || '未知'}；${selection.basis || '未知'}／${selection.scope || '未知'}。交易獨立標期；不混期求比，不代表因果。`));
      const steps = html('div'); steps.className = 'trace-steps';
      function step(label, company) {
        const card = html('article'); card.className = 'trace-step'; card.append(html('h3', label), html('p', `公司：${company?.name || '未知'}`)); steps.append(card); return card;
      }
      function amount(card, companyId, metric, label) {
        const result = traceAmount(companyId, metric, selection);
        const text = result.item ? `${result.item.value} ${result.item.unit} ${result.item.currency}` : `缺口：${result.reason}`;
        const row = html('p', `${label}：${text}；${selection.period || '期別未知'}`);
        if (result.item) row.append(actionButton('追查來源', () => showGraphEvidence(result.item.evidence_ids)));
        card.append(row);
      }
      const demand = step('1 需求', buyer);
      const records = edge.disclosures || [];
      const orders = records.filter(record => ['order_quantity', 'order_amount', 'backlog_amount'].includes(record.kind));
      if (!orders.length) demand.append(html('p', '給此供應商的訂單：未揭露'));
      [...orders, ...records.filter(record => ['sales_amount', 'purchase_amount'].includes(record.kind))].forEach(record => {
        const row = html('p', disclosureConflict(records.filter(other => other.kind === record.kind)) ? `${disclosureNames[record.kind]}：揭露衝突；${record.period || '期別未知'}` : disclosureText(record));
        row.append(actionButton('追查來源', () => showGraphEvidence(record.evidence_ids || []))); demand.append(row);
      });
      amount(demand, edge.target_id, 'capex', '客戶資本支出');
      demand.append(html('p', '客戶資本支出是公司整體支出，不能代替給此供應商的訂單。已實現銷貨／進貨不是訂單。'));
      const revenue = step('2 營收', supplier); amount(revenue, edge.source_id, 'revenue', '公司整體營收');
      const profit = step('3 利益', supplier), cash = step('4 現金流', supplier);
      amount(cash, edge.source_id, 'cfo', '營業現金流金額');
      const summary = financialSummary(index, edge.source_id, selection.period, selection.basis, selection.scope);
      analysisMetrics.forEach(metric => {
        const cell = summary.cells[metric], card = metric === 'fcf_margin' ? cash : profit;
        const row = html('p', `${ratioLabels[metric]}：${cell.value === null ? `缺口：${cell.reason}` : `${cell.value.toFixed(2)} %`}；${selection.period || '期別未知'}`);
        if (cell.value !== null) row.append(actionButton('追查來源', () => showRatioSource(cell, summary)));
        card.append(row);
      });
      cash.append(html('p', '自由現金流營收率使用公司整體資料，不代表這筆交易的現金流。'));
      panel.append(steps);
    }
    function renderResearch(ids, selection) {
      currentAnalysis = { ids, selection };
      const select = byId('research-company'); select.replaceChildren();
      if (!ids.includes(researchCompanyId)) researchCompanyId = ids.includes(centerId) ? centerId : ids[0];
      ids.forEach(id => {
        const option = html('option', index.entities.get(id)?.name || id); option.value = id; option.selected = id === researchCompanyId; select.append(option);
      });
      select.disabled = !ids.length;
      const panel = byId('research-signals'); panel.replaceChildren();
      if (!ids.length) { panel.append(html('p', '請選產業或公司；缺資料時請補來源。')); return; }
      researchSignals(index, researchCompanyId, selection).slice(0, 3).forEach(signal => {
        const card = html('article'); card.className = 'research-card';
        card.append(html('strong', `${signal.company?.name || signal.companyId}｜${signal.period || '期別未匯入'}`), html('p', signal.text), actionButton('提示來源', () => showSignalSource(signal)));
        panel.append(card);
      });
    }
    byId('research-company').addEventListener('change', () => {
      researchCompanyId = byId('research-company').value;
      if (currentAnalysis) renderResearch(currentAnalysis.ids, currentAnalysis.selection);
    });
    function sharePeriod(period) {
      return period ? period.replace(/(\d{4})-01-01~\1-12-31/g, '$1全年').replace(/(\d{4})-01-01~\1-06-30/g, '$1上半年') : '期別未知';
    }
    function shareLabel(strength) {
      const kind = strength.kind === 'purchase_share' ? '進貨占比' : '銷貨／營收占比';
      return strength.value === null ? `${strength.reason}｜${sharePeriod(strength.period)}` : `${kind}${strength.value}%｜${sharePeriod(strength.period)}`;
    }
    function renderAnalysis() {
      const ids = analysisCompanyIds(), group = `${centerId}|${ids.join('|')}`;
      if (group !== analysisGroup) { analysisGroup = group; analysisSelection = null; researchCompanyId = null; }
      const result = analysisComparison(index, ids, analysisSelection || {});
      const select = byId('analysis-period'); select.replaceChildren();
      result.periods.forEach((selection, number) => {
        const option = html('option', `${number === 0 ? '最新：' : ''}${selection.period}／${selection.basis}／${selection.scope}`);
        option.value = String(number);
        option.selected = selection.period === result.period && selection.basis === result.basis && selection.scope === result.scope;
        select.append(option);
      });
      select.disabled = !result.periods.length;
      const panel = byId('analysis-comparison'); panel.replaceChildren();
      renderResearch(ids, result);
      renderTrace(result);
      if (!ids.length) { panel.append(html('p', '請選產業或公司，以查看四率。')); return; }
      panel.append(html('p', `公司整體；不代表單筆交易。共用期別：${result.period || '未匯入'}；口徑：${result.basis || '未知'}／${result.scope || '未知'}。同比單位：百分點。`));
      const table = html('table'), head = html('tr');
      head.append(html('th', '公司'));
      Object.values(ratioLabels).forEach(label => head.append(html('th', label)));
      const thead = html('thead'); thead.append(head); table.append(thead);
      const body = html('tbody');
      result.rows.forEach(row => {
        const tr = html('tr'); tr.dataset.companyId = row.companyId;
        const company = html('th', row.company?.name || row.companyId); company.scope = 'row'; tr.append(company);
        Object.entries(ratioLabels).forEach(([metric, label]) => {
          const cell = row.cells[metric], td = html('td'); td.dataset.metric = metric;
          if (cell.value === null) td.append(html('span', `缺資料：${cell.reason}`));
          else {
            const button = actionButton(`${cell.value.toFixed(2)}%`, () => showRatioSource(cell, row));
            button.setAttribute('aria-label', `${row.company?.name} ${label} ${cell.value.toFixed(2)}% 查看來源`);
            const bar = html('span'); bar.className = `ratio-bar${cell.value < 0 ? ' negative' : ''}`;
            bar.style.width = `${Math.min(100, Math.abs(cell.value))}%`; bar.setAttribute('aria-hidden', 'true');
            td.append(button, bar, html('small', `同比 ${cell.delta == null ? '—' : `${cell.delta >= 0 ? '+' : ''}${cell.delta.toFixed(2)} 百分點`}`));
          }
          appendTrend(td, row, metric); tr.append(td);
        });
        body.append(tr);
      });
      table.append(body); panel.append(table);
    }
    byId('analysis-period').addEventListener('change', () => {
      analysisSelection = analysisPeriods(index, analysisCompanyIds())[Number(byId('analysis-period').value)];
      renderAnalysis();
    });
    const disclosureNames = { order_quantity: '下單量', order_amount: '下單金額', backlog_amount: '在手訂單', sales_amount: '已實現銷貨', purchase_amount: '已實現進貨', sales_share: '銷貨／營收占比', purchase_share: '進貨占比' };
    function disclosureText(record) {
      const label = disclosureNames[record.kind] || '交易';
      const share = ['sales_share', 'purchase_share'].includes(record.kind);
      const amount = record.kind !== 'order_quantity' && !share;
      const hasProof = Array.isArray(record.evidence_ids) && record.evidence_ids.length && record.evidence_ids.every(id => index.evidence.has(id));
      const complete = Number.isFinite(record.value) && record.value >= 0 && record.unit && record.unit !== 'unknown' && completePeriod(record.period) && hasProof && (!share || record.value <= 100 && record.unit === '%' && record.currency == null) && (!amount || record.currency && record.currency !== 'unknown');
      if (!complete) return `${label}：資料不完整；期別：${readable(record.period)}`;
      return `${label}：${record.value} ${record.unit}${amount ? ` ${record.currency}` : ''}；${completePeriod(record.period)}`;
    }
    function disclosureConflict(records) {
      return records.some((record, number) => records.slice(number + 1).some(other => record.kind === other.kind && completePeriod(record.period) === completePeriod(other.period) && (record.value !== other.value || record.unit !== other.unit || record.currency !== other.currency)));
    }
    function supplyLabel(edge) {
      const records = edge.disclosures || [], orders = records.filter(record => record.kind === 'order_quantity');
      if (disclosureConflict(orders)) return '下單量：揭露衝突';
      const quantities = orders.length ? orders.map(disclosureText).join('／') : '下單量未揭露';
      const amounts = records.filter(record => !['order_quantity', 'sales_share', 'purchase_share'].includes(record.kind));
      if (!amounts.length) return quantities;
      return `${quantities}；${disclosureConflict(amounts) ? '交易金額：揭露衝突' : amounts.map(disclosureText).join('／')}`;
    }
    function showDisclosures(edge, panel) {
      const records = edge.disclosures || [];
      if (!records.some(record => record.kind === 'order_quantity')) panel.append(html('p', '下單量未揭露'));
      if (disclosureConflict(records)) panel.append(html('p', '交易揭露衝突；不可擇一或合計。'));
      ['sales_share', 'purchase_share'].forEach(kind => {
        const strength = relationStrength(index, edge, kind);
        if (!strength.kind) return;
        const owner = kind === 'sales_share' ? edge.source_id : edge.target_id;
        panel.append(html('p', `${shareLabel(strength)}；分母：${strength.denominator}；披露公司：${index.entities.get(owner)?.name || owner}`));
      });
      records.forEach(record => {
        const row = html('p', disclosureText(record)); row.append(evidenceButton(record)); panel.append(row);
      });
    }
    function emphasizeEdges() {
      [...edgesLayer.children].forEach(group => {
        const unrelated = selectedEdgeId ? group.dataset.edgeId !== selectedEdgeId : ![group.dataset.sourceId, group.dataset.targetId].includes(selectedId);
        group.classList.toggle('muted', unrelated);
      });
    }
    function describe(id) {
      const detail = graphDetail(index, graph, visible, id), panel = byId('detail');
      panel.replaceChildren(); byId('financials').replaceChildren();
      byId('finance-panel').open = false;
      byId('evidence').replaceChildren(html('p', '請選取來源'));
      if (!detail) { panel.append(html('p', '請選取節點或連線；目前篩選中無此資料')); return; }
      const item = detail.item;
      panel.append(html('h3', detail.isEdge ? relationText(item) : item.name));
      if (detail.isEdge) {
        const source = graph.nodes.find(node => node.id === item.source_id);
        const target = graph.nodes.find(node => node.id === item.target_id);
        panel.append(html('p', `來源：${source?.name || item.source_id} → 對象：${target?.name || item.target_id}`),
          html('p', `產品／服務：${readable(item.product)}；期別：${readable(item.period)}；${statusText(item.status)}`), evidenceButton(item));
        if (item.predicate === 'supplies_to') showDisclosures(item, panel);
      } else {
        panel.append(html('p', kinds[item.kind] || '節點'), actionButton('以此為中心', () => setCenter(item.id)));
        if (detail.owner) panel.append(html('p', `匿名對象；披露公司：${detail.owner.name}（${detail.owner.id}）`));
        if (item.kind === 'product') panel.append(html('p', '提供相同產品／服務不代表競爭。'));
        if (item.kind === 'company') {
          panel.append(html('p', `代號：${readable(item.ticker)}；僅計目前圖中可見關係`));
          (index.roles.get(id) || []).filter(role => byId('pending').checked || role.status !== 'pending').forEach(role => {
            const row = html('p', `角色：${role.theme}／${role.stage}；${readable(role.product)}；期別：${readable(role.period)}；${statusText(role.status)}`);
            row.append(evidenceButton(role)); panel.append(row);
          });
          [['upstream', '上游供應商'], ['downstream', '下游客戶'], ['competitor', '競爭者']].forEach(([key, label]) => {
            panel.append(html('p', `${label}：${detail.counts[key]}${detail.counts[key] ? ' 筆可見關係' : '；目前沒有已記錄關係（或已篩除）'}`));
          });
          detail.relations.forEach(edge => {
            const otherId = edge.source_id === id ? edge.target_id : edge.source_id;
            const other = graph.nodes.find(node => node.id === otherId);
            panel.append(actionButton(`${relationText(edge)}：${other?.name || otherId}；${readable(edge.product)}；${readable(edge.period)}；${statusText(edge.status)}`, () => { selectedEdgeId = edge.id; traceEdgeId = edge.predicate === 'supplies_to' ? edge.id : null; byId('details-panel').open = true; describe(edge.id); renderTrace(); }));
          });
          panel.append(actionButton(comparisonIds.has(id) ? '移出財務比較' : '加入財務比較', () => {
            if (comparisonIds.has(id)) comparisonIds.delete(id); else comparisonIds.add(id);
            describe(id); renderGraphComparison();
            byId('comparison-panel').open = true;
            byId('comparison-panel').scrollIntoView({ block: 'nearest' });
          }));
        }
        detail.neighbors.forEach(({ edge, node }) => {
          const row = html('p', `${relationText(edge)}：`);
          row.append(actionButton(node.name, () => activate(node)), html('span', `；期別：${readable(edge.period)}；${statusText(edge.status)}`), evidenceButton(edge));
          panel.append(row);
        });
        if (!detail.records.length) panel.append(html('p', '目前沒有已記錄關係（或已篩除）'));
        detail.coverage.forEach(record => {
          const warnings = (record.warnings || []).map(warning => typeof warning === 'string' ? warning : [warning?.reason, warning?.error].filter(Boolean).map(readable).join('／') || '未知警告');
          panel.append(html('p', `資料缺漏：${record.missing.join('、') || '無'}；警告：${warnings.join('、') || '無'}`));
        });
      }
      panel.append(actionButton('全部相關來源', () => showGraphEvidence(detail.evidenceIds)));
      if (!detail.evidence.length) panel.append(html('p', '無證據／待查核'));
    }
    function renderFinancials() {
      const panel = byId('financials'); panel.replaceChildren();
      const detail = graphDetail(index, graph, visible, selectedId);
      if (!detail?.financials.length) { panel.append(html('p', '請選取公司；無財務資料')); return; }
      detail.financials.forEach(record => {
        const row = html('p', `${record.metric}：${record.value ?? '缺值'} ${readable(record.currency)}／${record.unit}；期別：${readable(record.period)}；口徑：${readable(record.basis)}／${readable(record.scope)}`);
        row.append(evidenceButton(record)); panel.append(row);
      });
    }
    function renderGraphComparison() {
      const panel = byId('comparison'); panel.replaceChildren();
      const companies = visible.nodes.filter(item => item.kind === 'company');
      for (const id of comparisonIds) if (!companies.some(item => item.id === id)) comparisonIds.delete(id);
      panel.append(html('p', `已選：${[...comparisonIds].map(id => index.entities.get(id)?.name || id).join('、') || '無'}`));
      const result = compare(index, [...comparisonIds], byId('metric').value, byId('period').value, { companies });
      if (!result.comparable) {
        const fields = { metric: '指標', period: '期別', rows: '公司觀測筆數', basis: '報表口徑', currency: '幣別', unit: '單位', scope: '範圍', value: '數值' };
        const reasons = result.reasons.map(reason => {
          const field = reason.split(':')[0];
          const explanation = reason.includes('incompatible') ? '不一致' : reason.includes('no companies') ? '尚未選取公司' : reason.includes('observations') ? '每家公司須恰有一筆' : '缺漏或不完整';
          return `${fields[field] || '資料'}：${explanation}`;
        });
        panel.append(html('p', `無法比較：${reasons.join('；')}`)); return;
      }
      result.rows.forEach(record => {
        const row = html('p', `${index.entities.get(record.company_id)?.name}：${record.value} ${record.currency}／${record.unit}；${record.period}／${record.basis}／${record.scope}`);
        row.append(evidenceButton(record)); panel.append(row);
      });
    }
    function activate(item) {
      byId('details-panel').open = true;
      if (suppressClick) { suppressClick = false; return; }
      selectedId = item.id; selectedEdgeId = null;
      draw();
      const current = [...nodesLayer.children].find(element => element.getAttribute('data-node-id') === item.id);
      if (current) current.focus();
    }
    function bindActivation(element, action) {
      element.addEventListener('click', action);
      element.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); action(); }
      });
    }
    function setCenter(id, record = true) {
      if (!graph.nodes.some(node => node.id === id)) return;
      if (record && id !== centerId) history.push(id);
      centerId = id; selectedId = id; selectedEdgeId = null; collapsed = false; limits = {};
      byId('direction').value = ''; positions = {};
      draw(); camera = fitCenteredGraph(visible, positions); applyCamera();
    }
    function draw(anchorId = centerId, refreshDetail = true) {
      const focused = document.activeElement?.getAttribute('data-node-id');
      visible = pagedCenteredGraph(graph, centerId, { direction: byId('direction').value, includePending: byId('pending').checked, collapsed, limits });
      if (!visible.nodes.some(node => node.id === selectedId)) selectedId = centerId;
      const layout = centeredLayout(visible, centerId);
      positions = Object.fromEntries(visible.nodes.map(node => [node.id, positions[node.id] || layout[node.id]]));
      zonesLayer.replaceChildren();
      const labels = { upstream: '上游供應商', downstream: '下游客戶', competitor: '競爭者', product: '產品／服務（提供關係）', classification: '分類／產業導航' };
      const more = byId('section-more'); more.replaceChildren();
      Object.entries(visible.remaining).forEach(([zone, count]) => {
        const button = actionButton(`${labels[zone]}：尚有 ${count} 個，查看更多`, () => {
          limits[zone] = (limits[zone] || 5) + 5; positions = {};
          draw(); camera = fitCenteredGraph(visible, positions); applyCamera();
        });
        button.dataset.zone = zone; more.append(button);
      });
      Object.entries(labels).forEach(([zone, label]) => {
        const points = visible.nodes.filter(node => node.id !== centerId && neighborZone(visible, centerId, node.id) === zone).map(node => positions[node.id]);
        if (points.length) zonesLayer.append(makeSVG('text', { x: points.reduce((sum, point) => sum + point.x, 0) / points.length, y: Math.min(...points.map(point => point.y)) - 60, class: 'zone-label', 'text-anchor': 'middle' }, label));
      });
      byId('back-center').disabled = history.length < 2;
      edgesLayer.replaceChildren(); nodesLayer.replaceChildren();
      visible.edges.forEach(edge => {
        const path = edgeGeometry(positions[edge.source_id], positions[edge.target_id]);
        const competing = edge.predicate === 'competes_with';
        const group = makeSVG('g', { class: `map-edge${competing ? ' competing' : ''}${edge.status === 'pending' ? ' pending' : ''}` });
        const line = makeSVG('path', { d: path, class: 'edge-line' });
        if (edge.predicate === 'supplies_to') {
          line.setAttribute('marker-end', 'url(#supply-arrow)');
          line.style.strokeWidth = String(relationStrength(index, edge).width);
        }
        const source = graph.nodes.find(node => node.id === edge.source_id).name;
        const target = graph.nodes.find(node => node.id === edge.target_id).name;
        const label = `${source} ${competing ? '競爭' : edge.predicate === 'supplies_to' ? '供貨給' : '連結'} ${target}${edge.status === 'pending' ? '（待查核）' : ''}`;
        const hit = makeSVG('path', { d: path, class: 'edge-hit', tabindex: 0, role: 'button', 'aria-label': label });
        hit.append(makeSVG('title', {}, label));
        bindActivation(hit, () => { if (suppressClick) { suppressClick = false; return; } selectedEdgeId = edge.id; traceEdgeId = edge.predicate === 'supplies_to' ? edge.id : null; byId('details-panel').open = true; describe(edge.id); renderTrace(); emphasizeEdges(); });
        group.dataset.edgeId = edge.id; group.dataset.sourceId = edge.source_id; group.dataset.targetId = edge.target_id;
        group.append(line, hit);
        if (edge.predicate === 'supplies_to') {
          const start = positions[edge.source_id], end = positions[edge.target_id];
          const full = supplyLabel(edge);
          const orders = (edge.disclosures || []).filter(record => record.kind === 'order_quantity');
          const otherKinds = [...new Set((edge.disclosures || []).filter(record => record.kind !== 'order_quantity').map(record => disclosureNames[record.kind] || '交易'))];
          const short = orders.length ? full.split('；').slice(0, 2).join('；') : `下單量未揭露${otherKinds.length ? `；${otherKinds.join('／')}` : ''}`;
          const dated = short.replace(/(\d{4})-01-01~\1-06-30/g, '$1上半年').replace(/(\d{4})-01-01~\1-12-31/g, '$1全年');
          const compact = Array.from(dated).length > 30 ? `${Array.from(dated).slice(0, 29).join('')}…` : dated;
          const badge = makeSVG('text', { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 - 12, class: 'supply-label', 'text-anchor': 'middle' }, compact);
          badge.append(makeSVG('title', {}, full)); group.append(badge);
          const strength = relationStrength(index, edge);
          const shareBadge = makeSVG('text', { x: (start.x + end.x) / 2, y: (start.y + end.y) / 2 + 12, class: 'supply-label share-label', 'text-anchor': 'middle' }, shareLabel(strength));
          const owner = strength.kind === 'purchase_share' ? edge.target_id : edge.source_id;
          shareBadge.append(makeSVG('title', {}, `分母：${strength.denominator || '未揭露'}；披露公司：${index.entities.get(owner)?.name || owner}`)); group.append(shareBadge);
        }
        edgesLayer.append(group);
      });
      visible.nodes.forEach(item => {
        const point = positions[item.id];
        const element = makeSVG('g', { transform: `translate(${point.x} ${point.y})`, class: `map-node ${item.kind}${selectedId === item.id ? ' selected' : ''}${centerId === item.id ? ' center' : ''}`, tabindex: 0, role: 'button', 'aria-label': `${kinds[item.kind] || '節點'}：${item.name}，查看詳情`, 'aria-expanded': item.id === centerId && !collapsed, 'data-node-id': item.id });
        element.append(makeSVG('title', {}, item.name), makeSVG('rect', { x: -90, y: -36, width: 180, height: 72, rx: item.kind === 'company' ? 8 : 24 }));
        const characters = Array.from(item.name || '未知');
        const label = makeSVG('text', { 'text-anchor': 'middle' });
        const lines = [characters.slice(0, 12).join(''), characters.slice(12, 24).join('') + (characters.length > 24 ? '…' : '')].filter(Boolean);
        lines.forEach((line, number) => label.append(makeSVG('tspan', { x: 0, y: lines.length === 1 ? 5 : -5 + number * 21 }, line)));
        element.append(label); bindActivation(element, () => activate(item));
        element.addEventListener('pointerdown', event => beginGesture(event, item.id));
        nodesLayer.append(element);
      });
      byId('map-empty').hidden = graph.nodes.some(item => item.kind !== 'root');
      byId('collapse-node').textContent = collapsed ? '展開中心一層' : '收合中心一層';
      applyCamera(); emphasizeEdges();
      if (refreshDetail) {
        if (selectedEdgeId && !visible.edges.some(edge => edge.id === selectedEdgeId)) selectedEdgeId = null;
        describe(selectedEdgeId || selectedId);
        renderGraphComparison(); renderAnalysis();
      }
      if (focused) [...nodesLayer.children].find(element => element.getAttribute('data-node-id') === focused)?.focus();
    }
    function beginGesture(event, nodeId = null) {
      if (event.button !== 0) return;
      event.stopPropagation(); suppressClick = false;
      gesture = { nodeId, start: localPoint(event), camera: { ...camera }, point: nodeId ? { ...positions[nodeId] } : null, moved: false, pointerId: event.pointerId };
      svg.setPointerCapture(event.pointerId);
    }
    svg.addEventListener('pointerdown', event => {
      if (event.target === svg || event.target === world) beginGesture(event);
    });
    svg.addEventListener('pointermove', event => {
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      const point = localPoint(event), dx = point.x - gesture.start.x, dy = point.y - gesture.start.y;
      if (Math.hypot(dx, dy) > 5) gesture.moved = true;
      if (!gesture.moved) return;
      if (gesture.nodeId === centerId) return;
      if (gesture.nodeId) {
        positions[gesture.nodeId] = { x: gesture.point.x + dx / camera.scale, y: gesture.point.y + dy / camera.scale };
        draw(undefined, false);
      } else { camera = { ...camera, x: gesture.camera.x + dx, y: gesture.camera.y + dy }; applyCamera(); }
    });
    function endGesture(event) {
      if (!gesture || event.pointerId !== gesture.pointerId) return;
      const finished = gesture; gesture = null; suppressClick = finished.moved;
      if (svg.hasPointerCapture(event.pointerId)) svg.releasePointerCapture(event.pointerId);
      // Pointer capture retargets click to the SVG; activate a tap explicitly.
      if (!finished.moved && finished.nodeId && event.type !== 'pointercancel') activate(graph.nodes.find(item => item.id === finished.nodeId));
      else if (finished.moved) setTimeout(() => { suppressClick = false; }, 0);
    }
    svg.addEventListener('pointerup', endGesture);
    svg.addEventListener('pointercancel', endGesture);
    svg.addEventListener('wheel', event => {
      event.preventDefault(); camera = zoomGraph(camera, event.deltaY < 0 ? 1.15 : 1 / 1.15, localPoint(event)); applyCamera();
    }, { passive: false });
    byId('zoom-in').addEventListener('click', () => { camera = zoomGraph(camera, 1.25); applyCamera(); });
    byId('zoom-out').addEventListener('click', () => { camera = zoomGraph(camera, .8); applyCamera(); });
    byId('fit-map').addEventListener('click', () => { camera = fitCenteredGraph(visible, positions); applyCamera(); });
    byId('collapse-node').addEventListener('click', () => { collapsed = !collapsed; positions = {}; draw(); });
    byId('back-center').addEventListener('click', () => { if (history.length > 1) { history.pop(); setCenter(history.at(-1), false); } });
    byId('reset-map').addEventListener('click', () => {
      centerId = 'map:root'; history = [centerId]; collapsed = false; limits = {}; positions = {}; selectedId = centerId; selectedEdgeId = null; comparisonIds.clear();
      byId('direction').value = ''; byId('pending').checked = true;
      byId('search').value = ''; byId('search-results').replaceChildren();
      byId('detail').replaceChildren(html('p', '請選取節點或連線'));
      draw(); camera = fitCenteredGraph(visible, positions); applyCamera();
    });
    byId('search').addEventListener('input', () => {
      const results = byId('search-results'); results.replaceChildren();
      const matches = searchGraph(graph, byId('search').value);
      if (byId('search').value.trim() && !matches.length) results.append(html('p', '無符合資料'));
      matches.forEach(item => {
        const button = html('button', `${kinds[item.kind] || '節點'}：${item.name}`); button.type = 'button';
        button.addEventListener('click', () => {
          setCenter(item.id); results.replaceChildren();
          [...nodesLayer.children].find(element => element.getAttribute('data-node-id') === item.id)?.focus();
        }); results.append(button);
      });
    });
    ['direction', 'pending'].forEach(id => byId(id).addEventListener('change', () => {
      positions = {}; draw();
    }));
    for (const metric of new Set(index.snapshot.observations.map(record => record.metric))) {
      const option = html('option', metric); option.value = metric; byId('metric').append(option);
    }
    for (const period of new Set(index.snapshot.observations.map(record => record.period).filter(completePeriod))) {
      const option = html('option', period); option.value = period; byId('period').append(option);
    }
    ['metric', 'period'].forEach(id => byId(id).addEventListener('change', renderGraphComparison));
    byId('finance-panel').addEventListener('toggle', () => { if (byId('finance-panel').open) renderFinancials(); });
    draw(); camera = fitCenteredGraph(visible, positions); applyCamera();
  }
  const api = { financialTrend, researchSignals, relationStrength, financialSummary, analysisPeriods, analysisComparison, pagedCenteredGraph, fitCenteredGraph, centeredGraph, centeredLayout, createIndex, filter, select, selectEvidence, compare, completePeriod, createGraph, createGraphState, expandGraph, collapseGraph, resetGraph, visibleGraph, searchGraph, focusGraph, graphRelations, layoutGraph, edgeGeometry, fitGraph, zoomGraph, graphDetail };
  if (typeof window !== 'undefined') window.IndustryMap = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  if (typeof document === 'undefined') return;
  const index = createIndex(JSON.parse(document.getElementById('snapshot').textContent));
  if (document.getElementById('map')) { startGraphUI(index); return; }
  // Legacy DOM hosts retain the original list behavior.
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
