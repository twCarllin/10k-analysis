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
    marker.append(makeSVG('path', { d: 'M 0 0 L 10 5 L 0 10 z', fill: '#476581' }));
    defs.append(marker);
    const world = makeSVG('g'), edgesLayer = makeSVG('g'), nodesLayer = makeSVG('g');
    world.append(edgesLayer, nodesLayer); svg.append(defs, world);
    let graphState = createGraphState(), positions = {}, selectedId = null, selectedEdgeId = null;
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
      } else {
        panel.append(html('p', kinds[item.kind] || '節點'));
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
            panel.append(actionButton(`${relationText(edge)}：${other?.name || otherId}；${statusText(edge.status)}`, () => { selectedEdgeId = edge.id; describe(edge.id); }));
          });
          panel.append(actionButton(comparisonIds.has(id) ? '移出財務比較' : '加入財務比較', () => {
            if (comparisonIds.has(id)) comparisonIds.delete(id); else comparisonIds.add(id);
            describe(id); renderGraphComparison();
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
      if (suppressClick) { suppressClick = false; return; }
      selectedId = item.id; selectedEdgeId = null;
      if (item.kind !== 'company') byId('direction').value = '';
      graphState = expandGraph(graphState, item.id);
      graphState = { ...graphState, focus: item.id };
      draw(item.id);
      const current = [...nodesLayer.children].find(element => element.getAttribute('data-node-id') === item.id);
      if (current) current.focus();
    }
    function bindActivation(element, action) {
      element.addEventListener('click', action);
      element.addEventListener('keydown', event => {
        if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); action(); }
      });
    }
    function draw(anchorId = selectedId || 'map:root', refreshDetail = true) {
      const focused = document.activeElement?.getAttribute('data-node-id');
      const direction = byId('direction').value;
      // Direction filters keep their anchor reachable only for this view.
      // Ordinary clicks must not become independent, persistent search roots.
      const directionalState = direction && selectedId
        ? { ...graphState, roots: [...new Set([...graphState.roots, selectedId])] }
        : graphState;
      visible = visibleGraph(graph, directionalState, { companyId: selectedId, direction, includePending: byId('pending').checked });
      positions = layoutGraph(visible, positions, anchorId);
      edgesLayer.replaceChildren(); nodesLayer.replaceChildren();
      visible.edges.forEach(edge => {
        const path = edgeGeometry(positions[edge.source_id], positions[edge.target_id]);
        const competing = edge.predicate === 'competes_with';
        const group = makeSVG('g', { class: `map-edge${competing ? ' competing' : ''}${edge.status === 'pending' ? ' pending' : ''}` });
        const line = makeSVG('path', { d: path, class: 'edge-line' });
        if (edge.predicate === 'supplies_to') line.setAttribute('marker-end', 'url(#supply-arrow)');
        const source = graph.nodes.find(node => node.id === edge.source_id).name;
        const target = graph.nodes.find(node => node.id === edge.target_id).name;
        const label = `${source} ${competing ? '競爭' : edge.predicate === 'supplies_to' ? '供貨給' : '連結'} ${target}${edge.status === 'pending' ? '（待查核）' : ''}`;
        const hit = makeSVG('path', { d: path, class: 'edge-hit', tabindex: 0, role: 'button', 'aria-label': label });
        hit.append(makeSVG('title', {}, label));
        bindActivation(hit, () => { if (suppressClick) { suppressClick = false; return; } selectedEdgeId = edge.id; describe(edge.id); });
        group.append(line, hit); edgesLayer.append(group);
      });
      visible.nodes.forEach(item => {
        const point = positions[item.id];
        const element = makeSVG('g', { transform: `translate(${point.x} ${point.y})`, class: `map-node ${item.kind}${selectedId === item.id ? ' selected' : ''}`, tabindex: 0, role: 'button', 'aria-label': `${kinds[item.kind] || '節點'}：${item.name}，展開`, 'aria-expanded': graphState.expanded.includes(item.id), 'data-node-id': item.id });
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
      byId('collapse-node').disabled = !selectedId;
      applyCamera();
      if (refreshDetail) {
        if (selectedEdgeId && !visible.edges.some(edge => edge.id === selectedEdgeId)) selectedEdgeId = null;
        describe(selectedEdgeId || selectedId);
        renderGraphComparison();
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
    byId('fit-map').addEventListener('click', () => { camera = fitGraph(visible, positions); applyCamera(); });
    byId('collapse-node').addEventListener('click', () => { graphState = collapseGraph(graphState, selectedId); draw(); });
    byId('reset-map').addEventListener('click', () => {
      graphState = resetGraph(); positions = {}; selectedId = null; selectedEdgeId = null; comparisonIds.clear();
      byId('direction').value = ''; byId('pending').checked = true;
      byId('search').value = ''; byId('search-results').replaceChildren();
      byId('detail').replaceChildren(html('p', '請選取節點或連線'));
      draw(); camera = fitGraph(visible, positions); applyCamera();
    });
    byId('search').addEventListener('input', () => {
      const results = byId('search-results'); results.replaceChildren();
      const matches = searchGraph(graph, byId('search').value);
      if (byId('search').value.trim() && !matches.length) results.append(html('p', '無符合資料'));
      matches.forEach(item => {
        const button = html('button', `${kinds[item.kind] || '節點'}：${item.name}`); button.type = 'button';
        button.addEventListener('click', () => {
          selectedId = item.id; selectedEdgeId = null;
          if (item.kind !== 'company') byId('direction').value = '';
          graphState = expandGraph(focusGraph(graph, graphState, item.id), item.id);
          draw(item.id);
          const point = positions[item.id]; camera = { ...camera, x: 500 - point.x * camera.scale, y: 325 - point.y * camera.scale };
          applyCamera(); results.replaceChildren();
          [...nodesLayer.children].find(element => element.getAttribute('data-node-id') === item.id)?.focus();
        }); results.append(button);
      });
    });
    ['direction', 'pending'].forEach(id => byId(id).addEventListener('change', () => {
      if (selectedId) graphState = expandGraph(graphState, selectedId);
      draw();
    }));
    for (const metric of new Set(index.snapshot.observations.map(record => record.metric))) {
      const option = html('option', metric); option.value = metric; byId('metric').append(option);
    }
    for (const period of new Set(index.snapshot.observations.map(record => record.period).filter(completePeriod))) {
      const option = html('option', period); option.value = period; byId('period').append(option);
    }
    ['metric', 'period'].forEach(id => byId(id).addEventListener('change', renderGraphComparison));
    byId('finance-panel').addEventListener('toggle', () => { if (byId('finance-panel').open) renderFinancials(); });
    draw(); camera = fitGraph(visible, positions); applyCamera();
  }
  const api = { createIndex, filter, select, selectEvidence, compare, completePeriod, createGraph, createGraphState, expandGraph, collapseGraph, resetGraph, visibleGraph, searchGraph, focusGraph, graphRelations, layoutGraph, edgeGeometry, fitGraph, zoomGraph, graphDetail };
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
