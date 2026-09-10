const PAPER_PAGE_SIZE = 20;
const MISSING_VALUE = '--';

const state = {
  mode: 'read',
  overview: null,
  papers: null,
  paperPage: 1,
  selectedPaperId: null,
  paperDetail: null,
};

const viewLabels = { overview: 'PROJECT OVERVIEW', papers: 'PAPER LIBRARY', 'paper-detail': 'PAPER WORKSPACE' };
const ENTRY_STATUS_OPTIONS = [
  ['unreviewed', '未审阅'],
  ['in_review', '审阅中'],
  ['needs_follow_up', '需要补充'],
];
const RELATION_OPTIONS = [
  ['explicit_directed_replacement', '明确替换'],
  ['explicit_directed_substitution', '明确取代'],
  ['series_or_structure_review_required', '系列/结构待复核'],
  ['manual_review', '人工录入'],
];
const PATH_STATUS_OPTIONS = [
  ['candidate', '候选路径'],
  ['text_confirmed_structure_pending', '文字确认，结构待确认'],
  ['structure_confirmed_pending_human_review', '结构确认，待人工审阅'],
  ['confirmed', '已确认'],
  ['manual_pending', '人工待补充'],
];
const STRUCTURE_REVIEW_OPTIONS = [
  ['needs_scheme_or_table_review', '需要 Scheme/Table 复核'],
  ['ready_for_visual_review', '可进行结构复核'],
  ['confirmed_by_si_smiles', 'SI SMILES 已确认'],
  ['manual_review', '人工录入'],
];
const STRUCTURE_CONFIRMATION_OPTIONS = [
  ['confirmed_by_si_smiles', 'SI SMILES 已确认'],
  ['manual_pending', '人工待确认'],
  ['needs_confirmation', '需要确认'],
];
const MOLECULE_ATTACHMENT_OPTIONS = [
  ['attachment_points_inferred', '连接位点已推理'],
  ['attachment_points_unresolved_source_anchor', '来源有候选，连接点未解出'],
  ['insufficient_visual_evidence', '图片证据不足'],
  ['connection_reviewed', '连接关系已人工复核'],
];
const MOLECULE_ASSEMBLY_OPTIONS = [
  ['fragment_only_requires_parent_assembly', '仅片段，待母体组装'],
  ['source_anchored_whole_molecule_candidate', '来源锚定的整分子候选'],
  ['not_assembled', '未组装'],
  ['assembly_reviewed', '组装结构已人工复核'],
];
const ENTRY_FIELD_GROUPS = [
  {
    label: '内容与证据',
    fields: [
      { key: 'page', label: '页码', control: 'number', placeholder: '例如 5' },
      { key: 'page_references', label: '图表 / 页码引用', control: 'text', placeholder: '例如 Figure 2 | Table 1' },
      { key: 'parent_compound', label: 'Parent compound', control: 'text', placeholder: '例如 12d' },
      { key: 'derived_compound', label: 'Derived compound', control: 'text', placeholder: '例如 12g' },
      { key: 'reported_from_group', label: 'Reported from group', control: 'text', placeholder: '例如 phenyl ring' },
      { key: 'reported_to_group', label: 'Reported to group', control: 'text', placeholder: '例如 thiophene' },
      { key: 'relation_type', label: 'Relation type', control: 'select', options: RELATION_OPTIONS },
      { key: 'compound_mentions', label: 'Compound mentions', control: 'text', placeholder: '例如 compounds 12d and 12g' },
      { key: 'activity', label: 'Activity', control: 'textarea', placeholder: '例如 decreased activity; IC50 = 10 nM' },
      { key: 'evidence_text', label: 'Evidence text', control: 'textarea', placeholder: '粘贴或修订支持该条目的原文证据' },
    ],
  },
  {
    label: '路径与结构判断',
    fields: [
      { key: 'path_status', label: 'Path status', control: 'select', options: PATH_STATUS_OPTIONS },
      { key: 'structure_review_status', label: 'Structure review status', control: 'select', options: STRUCTURE_REVIEW_OPTIONS },
      { key: 'structure_confirmation_status', label: 'Structure confirmation status', control: 'select', options: STRUCTURE_CONFIRMATION_OPTIONS },
    ],
  },
  {
    label: 'SMILES / RDKit 输入',
    fields: [
      { key: 'parent_smiles', label: 'Parent SI SMILES', control: 'smiles', placeholder: '输入 Parent SMILES' },
      { key: 'derived_smiles', label: 'Derived SI SMILES', control: 'smiles', placeholder: '输入 Derived SMILES' },
      { key: 'parent_canonical_smiles', label: 'Parent canonical SMILES', control: 'smiles', placeholder: '输入 Parent canonical SMILES' },
      { key: 'derived_canonical_smiles', label: 'Derived canonical SMILES', control: 'smiles', placeholder: '输入 Derived canonical SMILES' },
    ],
  },
];
const MOLECULE_PAIR_FIELD_GROUP = {
  label: '完整分子 pair 与结构推理',
  fields: [
    { key: 'parent_smiles', label: 'Parent full SMILES', control: 'smiles', placeholder: '输入修改前完整分子 SMILES' },
    { key: 'derived_smiles', label: 'Derived full SMILES', control: 'smiles', placeholder: '输入修改后完整分子 SMILES' },
    { key: 'fragment_smiles', label: 'Fragment SMILES', control: 'smiles', placeholder: '使用 [*:n] 标记片段连接端点' },
    { key: 'assembled_smiles', label: 'Assembled candidate SMILES', control: 'smiles', placeholder: '输入推理得到的完整分子候选 SMILES' },
    { key: 'attachment_status', label: 'Attachment status', control: 'select', options: MOLECULE_ATTACHMENT_OPTIONS },
    { key: 'assembly_status', label: 'Assembly status', control: 'select', options: MOLECULE_ASSEMBLY_OPTIONS },
    { key: 'inference_note', label: 'Connection inference note', control: 'textarea', placeholder: '记录骨架、R 基团和连接位置的推理依据' },
  ],
};
const LINEAGE_PAIR_FIELD_GROUP = {
  label: '优化迭代链与完整分子',
  fields: [
    { key: 'root_template', label: 'Root template', control: 'text', placeholder: '例如 1 / danuglipron' },
    { key: 'parent_smiles', label: 'Direct parent full SMILES', control: 'smiles', placeholder: '输入本轮直接母体的完整 SMILES' },
    { key: 'derived_smiles', label: 'Derived full SMILES', control: 'smiles', placeholder: '输入本轮衍生物的完整 SMILES' },
  ],
};
const $ = (selector) => document.querySelector(selector);
const $$ = (selector) => [...document.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? '').replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#039;');
}

function displayValue(value, fallback = MISSING_VALUE) {
  const text = String(value ?? '').trim();
  return text || fallback;
}

function formatNumber(value) { return new Intl.NumberFormat('en-US').format(Number(value || 0)); }

function shortText(value, length = 150) {
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > length ? `${text.slice(0, length - 1)}…` : text;
}

function paperReviewLabel(status) {
  return { unreviewed: '未审阅', in_review: '审阅中', needs_follow_up: '需要补充', reviewed: '已审阅' }[status] || displayValue(status);
}

function pipelineLabel(status) {
  return { text_ready: 'TEXT READY', evidence_review: 'EVIDENCE REVIEW', candidate_review: 'CANDIDATE REVIEW', path_review: 'PATH REVIEW', lineage: 'LINEAGE' }[status] || displayValue(status).replaceAll('_', ' ').toUpperCase();
}

function stageLabel(status) { return { complete: 'COMPLETE', ready: 'READY', pending: 'PENDING', in_progress: 'IN PROGRESS' }[status] || displayValue(status).toUpperCase(); }

function showToast(message) {
  const toast = $('#toast');
  toast.textContent = message;
  toast.classList.add('is-visible');
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => toast.classList.remove('is-visible'), 2600);
}

async function getJSON(url) {
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.error || `Request failed: ${response.status}`);
  }
  return response.json();
}

async function postJSON(url, payload) {
  const response = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload), cache: 'no-store' });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Request failed: ${response.status}`);
  return result;
}

async function deleteJSON(url) {
  const response = await fetch(url, { method: 'DELETE', cache: 'no-store' });
  const result = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(result.error || `Request failed: ${response.status}`);
  return result;
}

async function loadOverview() {
  state.overview = await getJSON('/api/overview');
  renderOverview();
  $('#syncLabel').textContent = 'SNAPSHOT READY';
}

function currentPaperFilters() {
  return { query: encodeURIComponent($('#paperSearch').value.trim()), pipeline: encodeURIComponent($('#paperStatusFilter').value), review: encodeURIComponent($('#paperReviewFilter').value) };
}

async function loadPapers() {
  const filters = currentPaperFilters();
  const url = `/api/papers?q=${filters.query}&status=${filters.pipeline}&review_status=${filters.review}&page=${state.paperPage}&page_size=${PAPER_PAGE_SIZE}`;
  $('#paperTableBody').innerHTML = '<tr><td class="empty-row" colspan="7">Loading Papers...</td></tr>';
  try {
    state.papers = await getJSON(url);
    renderPapers();
  } catch (error) {
    $('#paperTableBody').innerHTML = `<tr><td class="empty-row" colspan="7">${escapeHtml(error.message)}</td></tr>`;
  }
}

function renderPapers() {
  const result = state.papers;
  $('#paperResultMeta').textContent = `${formatNumber(result.total)} papers`;
  $('#paperPageMeta').textContent = result.total ? `PAGE ${result.page} / ${result.page_count}` : 'PAGE 0 / 0';
  $('#paperTableBody').innerHTML = result.items.length ? result.items.map((paper, index) => {
    const rowNumber = ((result.page - 1) * result.page_size) + index + 1;
    return `<tr data-paper-id="${escapeHtml(paper.paper_id)}"><td class="paper-index">${String(rowNumber).padStart(3, '0')}</td><td><div class="paper-cell"><strong>${escapeHtml(displayValue(paper.title, 'Untitled paper'))}</strong><span>${escapeHtml(displayValue(paper.paper_id))} · ${escapeHtml(displayValue(paper.source_folder))}</span></div></td><td class="doi-cell">${escapeHtml(displayValue(paper.doi, 'DOI unavailable'))}</td><td><div class="signal-cell"><span>${formatNumber(paper.evidence_count)} evidence</span><span>${formatNumber(paper.candidate_count)} candidates</span><span>${formatNumber(paper.explicit_path_count)} paths</span><span>${formatNumber(paper.molecule_object_count)} image objects</span><span>${formatNumber(paper.molecule_pair_count)} molecule pairs</span></div></td><td><span class="status-tag pipeline-${escapeHtml(paper.workflow_status)}">${escapeHtml(pipelineLabel(paper.workflow_status))}</span></td><td><span class="status-tag review-${escapeHtml(paper.review_status)}">${escapeHtml(paperReviewLabel(paper.review_status))}</span></td><td class="row-arrow">›</td></tr>`;
  }).join('') : '<tr><td class="empty-row" colspan="7">No Papers match this filter.</td></tr>';
  $$('#paperTableBody tr[data-paper-id]').forEach((row) => row.addEventListener('click', () => openPaper(row.dataset.paperId)));
  renderPaperPagination(result);
}

function renderPaperPagination(result) {
  if (!result.total || result.page_count <= 1) { $('#paperPagination').innerHTML = result.total ? '<span class="pagination-note">20 / page</span>' : ''; return; }
  const pages = [];
  for (let page = 1; page <= result.page_count; page += 1) if (page === 1 || page === result.page_count || Math.abs(page - result.page) <= 1) pages.push(page);
  const tokens = [];
  pages.forEach((page, index) => { if (index && page - pages[index - 1] > 1) tokens.push('<span class="pagination-gap">...</span>'); tokens.push(`<button class="page-button ${page === result.page ? 'is-active' : ''}" type="button" data-paper-page="${page}">${page}</button>`); });
  $('#paperPagination').innerHTML = `<span class="pagination-note">20 / page · ${formatNumber(result.total)} total</span><button class="page-button" type="button" data-paper-page="${result.page - 1}" ${result.page === 1 ? 'disabled' : ''}>‹</button>${tokens.join('')}<button class="page-button" type="button" data-paper-page="${result.page + 1}" ${result.page === result.page_count ? 'disabled' : ''}>›</button>`;
  $$('#paperPagination .page-button:not(:disabled)').forEach((button) => button.addEventListener('click', () => { state.paperPage = Number(button.dataset.paperPage); loadPapers(); }));
}

async function openPaper(paperId) {
  state.selectedPaperId = paperId;
  setView('paper-detail');
  $('#paperDetailWorkspace').innerHTML = '<div class="detail-loading"><span class="loading-bar"></span><strong>Loading Paper workspace...</strong><span>Aggregating unified review entries and attached structure evidence.</span></div>';
  try { state.paperDetail = await getJSON(`/api/papers/${encodeURIComponent(paperId)}`); renderPaperDetail(); } catch (error) { $('#paperDetailWorkspace').innerHTML = `<div class="error-box">${escapeHtml(error.message)}<button class="text-action" data-back-papers type="button">返回 Paper 库</button></div>`; $('#paperDetailWorkspace [data-back-papers]')?.addEventListener('click', () => setView('papers')); }
}

function renderOverview() {
  const { counts, queues, quality, stages, model, structure_generation: structures, structure_ocr: ocr } = state.overview;
  const metrics = [['PAPERS', counts.papers, 'corpus complete', '', 'all'], ['EVIDENCE STATEMENTS', counts.evidence, 'text layer', '', 'evidence_review'], ['CANDIDATE RECORDS', counts.candidate_records, `${formatNumber(queues.unresolved)} queued`, 'is-alert', 'candidate_review'], ['EXPLICIT PATHS', counts.explicit_paths, 'structure pending', 'is-coral', 'path_review'], ['GENERATED STRUCTURES', structures.smiles_slots, `${structures.paths_with_two_smiles} of ${counts.explicit_paths} paths`, '', 'path_review'], ['CONFIRMED PATHS', counts.confirmed_paths, 'human confirmation', 'is-alert', 'reviewed']];
  $('#metricGrid').innerHTML = metrics.map(([label, value, sub, extra, filter]) => `<button class="metric ${extra}" type="button" data-overview-filter="${filter}"><p class="metric-label">${label}</p><p class="metric-value">${formatNumber(value)}</p><p class="metric-sub">${sub}</p><span class="metric-hint">OPEN PAPER LIBRARY ↗</span></button>`).join('');
  $('#stageList').innerHTML = stages.map((stage, index) => { const filter = stage.id === 'corpus' ? 'all' : stage.id === 'text' ? 'text_ready' : stage.id === 'evidence' ? 'evidence_review' : stage.id === 'candidates' ? 'candidate_review' : 'path_review'; const count = stage.denominator ? `${formatNumber(stage.count)} / ${formatNumber(stage.denominator)}` : stage.status === 'complete' ? '100%' : stage.status === 'pending' ? '—' : formatNumber(stage.count); return `<button class="stage-row" type="button" data-overview-filter="${filter}"><span class="stage-number">0${index + 1}</span><span class="stage-name">${escapeHtml(stage.label)}<small>${escapeHtml(stage.detail || '')}</small></span><span class="stage-count">${escapeHtml(count)}</span><span class="stage-status"><i class="status-dot ${escapeHtml(stage.status)}"></i>${escapeHtml(stageLabel(stage.status))}</span></button>`; }).join('');
  $('#queueTotal').textContent = formatNumber(queues.unresolved);
  $('#queueList').innerHTML = [['HIGH PRIORITY', queues.high_priority, 'unresolved path records', 'high'], ['MEDIUM PRIORITY', queues.medium_priority, 'unresolved path records', 'medium'], ['EXPLICIT STRUCTURE REVIEW', counts.explicit_paths, 'text paths awaiting structure confirmation', 'structure'], ['FINAL CONFIRMATION', counts.confirmed_paths, 'paths promoted to final dataset', 'final']].map(([label, count, sub, kind]) => `<div class="queue-item"><div class="queue-item-copy"><strong>${label}</strong><span>${sub}</span></div><span class="queue-count ${kind}">${formatNumber(count)}</span></div>`).join('');
  $('#qualityStrip').innerHTML = `<span class="quality-title">MODEL / DATA QUALITY</span><div class="quality-items"><div class="quality-item ok"><strong>${quality.proposals}</strong><span>proposals</span></div><div class="quality-item ok"><strong>${quality.rdkit_valid}</strong><span>RDKit valid</span></div><div class="quality-item warn"><strong>${quality.rdkit_invalid}</strong><span>RDKit invalid</span></div><div class="quality-item ok"><strong>${quality.inference_errors}</strong><span>inference errors</span></div><div class="quality-item"><strong>${ocr.attempted_rows}/${ocr.candidate_rows}</strong><span>structure OCR</span></div><div class="quality-item warn"><strong>${ocr.pending_rows}</strong><span>OCR pending</span></div></div><div class="model-note">DECIMER ${escapeHtml(model.version)}<br />${escapeHtml(model.gpu)}</div>`;
  $$('[data-overview-filter]').forEach((button) => button.addEventListener('click', () => navigateToPapers(button.dataset.overviewFilter)));
}

function renderProgress(stages) {
  return `<div class="progress-grid">${stages.map((stage, index) => { const percent = stage.denominator ? Math.round((Number(stage.count) / Number(stage.denominator)) * 100) : 0; return `<div class="progress-stage"><div class="progress-stage-head"><span class="progress-index">0${index + 1}</span><strong>${escapeHtml(stage.label)}</strong><span class="progress-status ${escapeHtml(stage.status)}">${escapeHtml(stageLabel(stage.status))}</span></div><div class="progress-track"><span style="width:${Math.max(0, Math.min(percent, 100))}%"></span></div><div class="progress-detail"><span>${escapeHtml(stage.detail || '')}</span><strong>${formatNumber(stage.count)} / ${formatNumber(stage.denominator)}</strong></div></div>`; }).join('')}</div>`;
}

function renderStructure(item) {
  const structure = item.structure;
  if (!structure) return `<div class="structure-placeholder">SMILES / RDKit result ${MISSING_VALUE}</div>`;
  const image = structure.path_image_url || structure.parent_image_url || structure.derived_image_url;
  const expression = structure.structure_expression || item.auto_fill?.structure_expression;
  const representation = structure.representation_kind || item.auto_fill?.structure_representation_kind;
  const isGeneric = representation && representation !== 'exact_si_smiles';
  const structureVisual = image ? `<img class="entry-structure-image" src="${escapeHtml(image)}" alt="${escapeHtml(displayValue(item.candidate?.parent_compound, 'parent'))} to ${escapeHtml(displayValue(item.candidate?.derived_compound, 'derived'))} SMILES-generated structure" /><p class="image-label">Primary display rendered uniformly from SI SMILES with RDKit. Article image remains evidence only.</p>` : isGeneric && expression ? `<div class="generic-structure-expression"><span>STRUCTURE EXPRESSION</span><strong>${escapeHtml(expression)}</strong>${structure.attachment_points ? `<small>Attachment points: ${escapeHtml(structure.attachment_points)}</small>` : ''}<p>PDF 中仅明确了 R 基团或连接键表达，未将其扩展为未经验证的完整分子。</p></div>` : '<div class="structure-placeholder">SMILES / RDKit image --</div>';
  if (isGeneric) return structureVisual;
  return `${structureVisual}<div class="smiles-pair"><div><span>PARENT / SI SMILES</span><code>${escapeHtml(displayValue(structure.parent_canonical_smiles || structure.parent_smiles))}</code></div><div><span>DERIVED / SI SMILES</span><code>${escapeHtml(displayValue(structure.derived_canonical_smiles || structure.derived_smiles))}</code></div></div>`;
}

function renderMoleculePair(item) {
  const pair = item.molecule_pair || {};
  const parent = pair.parent_object || {};
  const derived = pair.derived_object || {};
  const crop = (url, label, object) => url
    ? `<a class="molecule-pair-crop" href="${escapeHtml(url)}" target="_blank" rel="noreferrer"><img src="${escapeHtml(url)}" alt="${escapeHtml(label)} ${escapeHtml(displayValue(object.compound_label, 'object'))} source crop" /><span>${escapeHtml(label)} · ${escapeHtml(displayValue(object.compound_label, 'unlabeled'))}</span></a>`
    : `<div class="molecule-pair-crop molecule-pair-crop-missing"><span>${escapeHtml(label)}</span><strong>--</strong></div>`;
  const smiles = (label, value) => `<div class="molecule-pair-smiles"><span>${escapeHtml(label)}</span><code>${escapeHtml(displayValue(value))}</code></div>`;
  const completeStructure = (side, label, compound, smilesValue, imageUrl) => {
    const visual = imageUrl
      ? `<img class="entry-structure-image" src="${escapeHtml(imageUrl)}" alt="${escapeHtml(label)} ${escapeHtml(displayValue(compound, 'complete molecule'))} rendered from full SMILES" />`
      : '<div class="structure-placeholder molecule-pair-structure-pending">--</div>';
    return `<div class="molecule-pair-structure-card"><div class="molecule-pair-structure-heading"><span>${escapeHtml(label)}</span><strong>${escapeHtml(displayValue(compound))}</strong></div>${visual}<p class="image-label">${imageUrl ? '完整分子由 SMILES 统一使用 RDKit 重绘。' : '完整分子 SMILES 待补，暂不生成结构图。'}</p><div class="molecule-pair-full-smiles"><span>FULL ${escapeHtml(side)} SMILES</span><code>${escapeHtml(displayValue(smilesValue))}</code></div></div>`;
  };
  const parentSmiles = pair.parent_canonical_smiles && pair.parent_canonical_smiles !== MISSING_VALUE ? pair.parent_canonical_smiles : pair.parent_smiles;
  const derivedSmiles = pair.derived_canonical_smiles && pair.derived_canonical_smiles !== MISSING_VALUE ? pair.derived_canonical_smiles : pair.derived_smiles;
  if (pair.pair_kind === 'compound_optimization_lineage') {
    return `<div class="molecule-pair-review lineage-molecule-pair"><div class="molecule-pair-status"><span class="status-tag review-needs_follow_up">${escapeHtml(pair.relation_status || pair.pair_status)}</span><span>${escapeHtml(displayValue(pair.lineage_id))} · ROOT TEMPLATE: <strong>${escapeHtml(displayValue(pair.root_template_label))}</strong></span></div><div class="molecule-pair-complete-structure"><div class="molecule-pair-structure-grid">${completeStructure('PARENT', 'DIRECT PARENT / BEFORE', item.candidate?.parent_compound, parentSmiles, pair.parent_complete_structure_image_url)}<span class="molecule-pair-arrow">→</span>${completeStructure('DERIVED', 'DERIVED COMPOUND / AFTER', item.candidate?.derived_compound, derivedSmiles, pair.derived_complete_structure_image_url)}</div></div><div class="molecule-pair-facts lineage-pair-facts"><div><span>ROOT TEMPLATE</span><strong>${escapeHtml(displayValue(pair.root_template_label))}</strong></div><div><span>DIRECT EDGE</span><strong>${escapeHtml(displayValue(pair.lineage_edge_id))}</strong></div><div><span>RELATION CONFIDENCE</span><strong>${escapeHtml(displayValue(pair.relation_confidence))}</strong></div></div></div>`;
  }
  return `<div class="molecule-pair-review"><div class="molecule-pair-status"><span class="status-tag review-needs_follow_up">${escapeHtml(pair.pair_status || 'requires_structure_review')}</span><span>每个审阅条目是一组完整 parent → derived 分子；PDF crop 仅作为来源证据。</span></div><div class="molecule-pair-complete-structure"><div class="molecule-pair-structure-grid">${completeStructure('PARENT', 'BEFORE / PARENT COMPLETE MOLECULE', item.candidate?.parent_compound, parentSmiles, pair.parent_complete_structure_image_url)}<span class="molecule-pair-arrow">→</span>${completeStructure('DERIVED', 'AFTER / DERIVED COMPLETE MOLECULE', item.candidate?.derived_compound, derivedSmiles, pair.derived_complete_structure_image_url)}</div></div><div class="molecule-pair-smiles-grid">${smiles('FRAGMENT SMILES / ENDPOINT MARKED', pair.fragment_smiles)}${smiles('ASSEMBLED SMILES / DERIVED ALIAS', pair.assembled_smiles)}</div><div class="molecule-pair-facts"><div><span>ATTACHMENT</span><strong>${escapeHtml(displayValue(pair.attachment_status))}</strong></div><div><span>ASSEMBLY</span><strong>${escapeHtml(displayValue(pair.assembly_status))}</strong></div><div><span>INFERENCE REVIEW</span><strong>${escapeHtml(displayValue(pair.review_status))}</strong></div></div><p class="molecule-pair-note"><span>CONNECTION INFERENCE</span>${escapeHtml(displayValue(pair.inference_note))}</p><div class="molecule-pair-source-evidence"><div class="molecule-pair-source-heading"><span>PDF SOURCE EVIDENCE</span><small>用于核对对象定位，不作为主结构图</small></div><div class="molecule-pair-crops">${crop(pair.parent_crop_url, 'PARENT OBJECT', parent)}<span class="molecule-pair-arrow">→</span>${crop(pair.derived_crop_url, 'DERIVED OBJECT', derived)}</div></div></div>`;
}

function renderOcsrResults(proposals) {
  if (!proposals.length) return `<div class="entry-ocsr-empty">OCSR result ${MISSING_VALUE}</div>`;
  return `<div class="entry-ocsr-list">${proposals.map((proposal) => { const label = proposal.compound_id || proposal.compound_ids || proposal.candidate_id; const status = [proposal.region_kind, proposal.rdkit_status, proposal.proposal_quality].filter(Boolean).join(' · '); const source = proposal.source_pdf ? `${proposal.source_pdf} · p. ${displayValue(proposal.page)}` : ''; return `<div class="entry-ocsr"><div><strong>${escapeHtml(displayValue(label))}</strong><span>${escapeHtml(displayValue(status))}</span>${source ? `<small>${escapeHtml(source)}</small>` : ''}</div><code>${escapeHtml(displayValue(proposal.canonical_smiles || proposal.raw_smiles))}</code>${proposal.crop_url ? `<a href="${escapeHtml(proposal.crop_url)}" target="_blank" rel="noreferrer">OCSR input crop ↗</a>` : ''}</div>`; }).join('')}</div>`;
}

function itemFieldValue(item, key) {
  const evidence = item?.evidence || {};
  const candidate = item?.candidate || {};
  const path = item?.path || {};
  const structure = item?.structure || {};
  const moleculePair = item?.molecule_pair || {};
  const values = {
    page: item?.page,
    page_references: item?.page_references || path.page_references,
    parent_compound: candidate.parent_compound || path.parent_compound || structure.parent_compound,
    derived_compound: candidate.derived_compound || path.derived_compound || structure.derived_compound,
    reported_from_group: candidate.from_group || path.from_group,
    reported_to_group: candidate.to_group || path.to_group,
    relation_type: candidate.relation_type,
    compound_mentions: item?.compound_mentions || evidence.compound_mentions,
    activity: item?.activity || candidate.activity || evidence.activity_mentions || path.activity,
    evidence_text: evidence.evidence_text || candidate.evidence_text || path.evidence_text,
    path_status: path.path_status || structure.path_status,
    structure_review_status: candidate.structure_review_status || path.structure_review_status,
    structure_confirmation_status: path.structure_confirmation_status || structure.confirmation_status,
    parent_smiles: moleculePair.parent_smiles || structure.parent_smiles,
    derived_smiles: moleculePair.derived_smiles || structure.derived_smiles,
    parent_canonical_smiles: moleculePair.parent_canonical_smiles || structure.parent_canonical_smiles,
    derived_canonical_smiles: moleculePair.derived_canonical_smiles || structure.derived_canonical_smiles,
    fragment_smiles: moleculePair.fragment_smiles,
    assembled_smiles: moleculePair.assembled_smiles,
    attachment_status: moleculePair.attachment_status,
    assembly_status: moleculePair.assembly_status,
    inference_note: moleculePair.inference_note,
    root_template: moleculePair.root_template_label,
    review_status: item?.review_status,
    correction_note: item?.correction_note,
    review_note: item?.review_note,
  };
  const value = values[key];
  return key === 'page' ? (Number(value) > 0 ? String(value) : '') : String(value ?? '');
}

function selectOptions(options, current) {
  const known = options.map(([value]) => value);
  const custom = current && !known.includes(current) ? `<option value="${escapeHtml(current)}" selected>当前值：${escapeHtml(current)}</option>` : '';
  return `<option value="">-- 未设置 --</option>${custom}${options.map(([value, label]) => `<option value="${escapeHtml(value)}" ${current === value ? 'selected' : ''}>${escapeHtml(label)}</option>`).join('')}`;
}

function renderEntryField(field, item = {}, scope = 'entry') {
  const current = itemFieldValue(item, field.key);
  const attributes = `data-entry-field="${escapeHtml(field.key)}" data-entry-scope="${escapeHtml(scope)}"`;
  let control;
  if (field.control === 'select') {
    control = `<select ${attributes}>${selectOptions(field.options, current)}</select>`;
  } else if (field.control === 'textarea') {
    control = `<textarea ${attributes} placeholder="${escapeHtml(field.placeholder || '')}">${escapeHtml(current)}</textarea>`;
  } else {
    const numberAttributes = field.control === 'number' ? ' min="1" step="1" inputmode="numeric"' : '';
    const pattern = field.control === 'smiles' ? ' pattern="[A-Za-z0-9@+\\-\\[\\]()=#$%./\\\\*:]+"' : '';
    control = `<input ${attributes} type="${field.control === 'number' ? 'number' : 'text'}" value="${escapeHtml(current)}" placeholder="${escapeHtml(field.placeholder || '')}"${numberAttributes}${pattern} />`;
  }
  return `<label class="edit-field entry-edit-field entry-field-${escapeHtml(field.key)}"><span>${escapeHtml(field.label)}</span>${control}</label>`;
}

function renderEntryFields(item = {}, scope = 'entry') {
  const groups = item?.source_kind === 'molecule_pair'
    ? ENTRY_FIELD_GROUPS.filter((group) => group.label !== 'SMILES / RDKit 输入')
    : ENTRY_FIELD_GROUPS;
  return `<div class="entry-edit-fields">${groups.map((group) => `<fieldset class="entry-field-group"><legend>${escapeHtml(group.label)}</legend><div class="entry-field-grid">${group.fields.map((field) => renderEntryField(field, item, scope)).join('')}</div></fieldset>`).join('')}</div>`;
}

function renderMoleculePairFields(item) {
  if (item?.source_kind !== 'molecule_pair') return '';
  const group = item?.molecule_pair?.pair_kind === 'compound_optimization_lineage'
    ? LINEAGE_PAIR_FIELD_GROUP
    : MOLECULE_PAIR_FIELD_GROUP;
  return `<fieldset class="entry-field-group molecule-pair-edit-group"><legend>${escapeHtml(group.label)}</legend><div class="entry-field-grid">${group.fields.map((field) => renderEntryField(field, item)).join('')}</div></fieldset>`;
}

function readEntryPayload(container, scope = 'entry') {
  const payload = {};
  container.querySelectorAll(`[data-entry-field][data-entry-scope="${CSS.escape(scope)}"]`).forEach((field) => {
    payload[field.dataset.entryField] = field.value;
  });
  return payload;
}

function renderReviewControls(item) {
  const locked = item.review_status === 'reviewed' || state.mode !== 'edit' || state.paperDetail.paper.review_status === 'reviewed';
  if (locked) return `<div class="entry-review-readonly"><span class="summary-label">ENTRY REVIEW</span><strong class="status-tag review-${escapeHtml(item.review_status)}">${escapeHtml(paperReviewLabel(item.review_status))}</strong><p>${escapeHtml(displayValue(item.review_note, 'No review note.'))}</p>${item.review_status === 'reviewed' ? '<small>该条目已审阅，保持只读。</small>' : state.mode !== 'edit' ? '<small>切换到修改模式后，可审阅未完成条目。</small>' : '<small>所属 Paper 已审阅，保持只读。</small>'}</div>`;
  const decisionFields = [
    { key: 'correction_note', label: '条目修订说明', control: 'textarea', placeholder: '记录此条目的修订内容' },
    { key: 'review_note', label: '条目审阅备注', control: 'textarea', placeholder: '记录此条目的判断依据' },
  ];
  return `<div class="entry-review-editor">${renderEntryFields(item)}${renderMoleculePairFields(item)}<fieldset class="entry-field-group entry-decision-group"><legend>审阅结论</legend><div class="entry-field-grid entry-decision-grid"><label class="edit-field entry-edit-field"><span>条目状态</span><select data-entry-field="review_status" data-entry-scope="entry">${selectOptions(ENTRY_STATUS_OPTIONS, item.review_status)}</select></label>${decisionFields.map((field) => renderEntryField(field, item)).join('')}</div></fieldset><div class="entry-actions"><button class="save-entry-button" type="button" data-save-item="${escapeHtml(item.review_item_id)}">保存草稿</button><button class="confirm-entry-button" type="button" data-confirm-item="${escapeHtml(item.review_item_id)}">确认并同步</button><button class="delete-entry-button" type="button" data-delete-item="${escapeHtml(item.review_item_id)}">删除条目</button></div></div>`;
}

function renderReviewItem(item, index) {
  const candidate = item.candidate || {};
  const path = item.path || {};
  const compoundPair = candidate.parent_compound || candidate.derived_compound ? `${escapeHtml(displayValue(candidate.parent_compound))} <span class="pair-arrow">→</span> ${escapeHtml(displayValue(candidate.derived_compound))}` : MISSING_VALUE;
  const modification = [candidate.from_group || path.from_group, candidate.to_group || path.to_group].filter(Boolean).join(' → ');
  const evidenceText = item.evidence?.evidence_text || candidate.evidence_text || path.evidence_text;
  const pathStatus = path.structure_confirmation_status || path.path_status || candidate.path_status;
  const structureReviewStatus = candidate.structure_review_status || path.structure_review_status;
  const sourceUrl = path.evidence_page_url || '';
  const autoFill = item.auto_fill;
  const autoFillBadge = autoFill ? `<div class="auto-fill-meta"><span class="auto-fill-status">AUTO-FILL · ${escapeHtml(autoFill.auto_fill_status || MISSING_VALUE)}</span><span>${escapeHtml(autoFill.structure_representation_kind || 'text only')}</span>${autoFill.structure_source_locator ? `<span>${escapeHtml(autoFill.structure_source_locator)}</span>` : ''}</div>` : '';
  const structureBlock = item.source_kind === 'molecule_pair' ? renderMoleculePair(item) : renderStructure(item);
  return `<article class="review-item" data-review-item="${escapeHtml(item.review_item_id)}"><div class="review-item-head"><div><span class="record-kicker">${String(index + 1).padStart(3, '0')} · ${escapeHtml(displayValue(item.review_item_id))}</span><h4>${compoundPair}</h4><p>p. ${escapeHtml(displayValue(item.page))} · ${escapeHtml(displayValue(item.page_references))}</p></div><span class="status-tag review-${escapeHtml(item.review_status)}">${escapeHtml(paperReviewLabel(item.review_status))}</span></div>${autoFillBadge}<div class="review-item-grid"><div class="entry-facts"><div><h5>REPORTED MODIFICATION</h5><p class="modification">${escapeHtml(displayValue(modification))}</p></div><div><h5>TEXT EVIDENCE</h5><p>${escapeHtml(displayValue(evidenceText))}</p>${sourceUrl ? `<a class="detail-link" href="${escapeHtml(sourceUrl)}" target="_blank" rel="noreferrer">Open source page evidence ↗</a>` : ''}</div><div><h5>ACTIVITY</h5><p class="activity-value">${escapeHtml(displayValue(item.activity))}</p></div><div class="entry-meta-grid"><div><span>COMPOUND MENTIONS</span><strong>${escapeHtml(displayValue(item.compound_mentions))}</strong></div><div><span>PATH STATUS</span><strong>${escapeHtml(displayValue(pathStatus))}</strong></div><div><span>STRUCTURE REVIEW</span><strong>${escapeHtml(displayValue(structureReviewStatus))}</strong></div><div><span>OCSR PROPOSALS</span><strong>${formatNumber(item.proposals.length)}</strong></div></div></div><div class="entry-structure"><h5>${item.source_kind === 'molecule_pair' ? 'MOLECULE PAIR / COMPLETE STRUCTURES' : 'SMILES / RDKIT STRUCTURE'}</h5>${structureBlock}</div></div><div class="entry-ocsr-block"><h5>OCSR RESULTS</h5>${renderOcsrResults(item.proposals)}</div><div class="entry-review-block"><h5>REVIEW THIS ENTRY</h5>${renderReviewControls(item)}</div></article>`;
}

function renderReviewItems(items) {
  if (!items.length) return `<div class="empty-state">No review entries are attached to this Paper.</div>`;
  return `<div class="review-item-list">${items.map(renderReviewItem).join('')}</div>`;
}

function renderAddReviewItemForm() {
  const emptyItem = { review_status: 'unreviewed' };
  return `<div class="add-entry-wrap"><button class="secondary-button add-entry-toggle" type="button" data-toggle-add-entry>+ 新增复核条目</button><form class="add-entry-form" id="addReviewItemForm" hidden><div class="add-entry-heading"><div><strong>新增人工复核条目</strong><span>保存后会进入当前 Paper 的独立审阅层。</span></div></div>${renderEntryFields(emptyItem, 'add')}<fieldset class="entry-field-group entry-decision-group"><legend>审阅结论</legend><div class="entry-field-grid entry-decision-grid"><label class="edit-field entry-edit-field"><span>条目状态</span><select data-entry-field="review_status" data-entry-scope="add">${selectOptions(ENTRY_STATUS_OPTIONS, 'unreviewed')}</select></label><label class="edit-field entry-edit-field"><span>条目修订说明</span><textarea data-entry-field="correction_note" data-entry-scope="add" placeholder="记录此条目的修订内容"></textarea></label><label class="edit-field entry-edit-field"><span>条目审阅备注</span><textarea data-entry-field="review_note" data-entry-scope="add" placeholder="记录此条目的判断依据"></textarea></label></div></fieldset><p class="form-hint">页码需要为正整数；SMILES 将在保存时校验格式。缺失字段可以留空，页面会显示为 --。</p><div class="edit-actions"><button class="save-paper-button" type="submit">保存新增条目</button><button class="secondary-button" type="button" data-cancel-add-entry>取消</button></div></form></div>`;
}

function renderPaperReview(detail) {
  const paper = detail.paper;
  const locked = paper.review_status === 'reviewed';
  if (state.mode !== 'edit' || locked) return `<div class="review-summary"><div><span class="summary-label">PAPER REVIEW STATUS</span><strong class="status-tag review-${escapeHtml(paper.review_status)}">${escapeHtml(paperReviewLabel(paper.review_status))}</strong></div><div><span class="summary-label">LAST UPDATED</span><strong>${escapeHtml(paper.review_updated_at ? new Date(paper.review_updated_at).toLocaleString('zh-CN') : 'Not yet')}</strong></div><div class="review-summary-note"><span class="summary-label">PAPER REVIEW NOTE</span><p>${escapeHtml(displayValue(paper.review_note, 'No review note recorded.'))}</p></div><p class="locked-note">${locked ? '该 Paper 已标记为已审阅，当前保持只读。' : '当前为阅读模式。切换到修改模式后，可修改尚未完成审阅的 Paper。'}</p></div>`;
  return `<form class="paper-edit-form" id="paperEditForm"><div class="edit-mode-banner"><span class="lock-dot"></span><strong>修改模式</strong><span>Paper 总状态和条目审阅都保存到独立审阅文件，不修改原始数据。</span></div><label class="edit-field"><span>标题修订</span><input id="paperTitleEdit" type="text" value="${escapeHtml(displayValue(paper.title_override || paper.title_original || paper.title, ''))}" /></label><div class="original-value"><span>原始标题</span><strong>${escapeHtml(displayValue(paper.title_original || paper.title))}</strong></div><label class="edit-field"><span>Paper 审阅状态</span><select id="paperReviewStatusEdit"><option value="unreviewed" ${paper.review_status === 'unreviewed' ? 'selected' : ''}>未审阅</option><option value="in_review" ${paper.review_status === 'in_review' ? 'selected' : ''}>审阅中</option><option value="needs_follow_up" ${paper.review_status === 'needs_follow_up' ? 'selected' : ''}>需要补充</option><option value="reviewed" ${paper.review_status === 'reviewed' ? 'selected' : ''}>已审阅</option></select></label><label class="edit-field"><span>Paper 内容修订说明</span><textarea id="paperCorrectionEdit">${escapeHtml(paper.correction_note)}</textarea></label><label class="edit-field"><span>Paper 审阅备注</span><textarea id="paperNoteEdit">${escapeHtml(paper.review_note)}</textarea></label><div class="edit-actions"><button class="save-paper-button" type="submit">保存 Paper 审阅</button><button class="secondary-button" id="cancelPaperEdit" type="button">取消</button><button class="secondary-button" id="restorePaperEdit" type="button">恢复原始值</button></div></form>`;
}

function renderCompoundLineages(detail) {
  const lineages = Array.isArray(detail?.compound_lineages) ? detail.compound_lineages : [];
  const edgeCount = Array.isArray(detail?.compound_lineage_edges) ? detail.compound_lineage_edges.length : 0;
  if (!lineages.length) {
    return '<section class="detail-section compound-lineage-section" id="compound-lineage-section"><div class="section-heading"><div><p class="section-label">COMPOUND OPTIMIZATION LINEAGE</p><h3>修改迭代链</h3></div><span class="section-count">0 edges</span></div><div class="empty-state">当前 Paper 尚未建立有证据支持的修改迭代链。</div></section>';
  }
  const activityText = (rows) => {
    if (!Array.isArray(rows) || !rows.length) return MISSING_VALUE;
    return rows.map((row) => `${displayValue(row.metric)} ${displayValue(row.qualifier, '=')} ${displayValue(row.value)}${row.unit && row.unit !== MISSING_VALUE ? ` ${row.unit}` : ''}`).join('; ');
  };
  const edgeRow = (edge) => {
    const parent = edge.parent || {};
    const derived = edge.derived || {};
    const parentLabel = parent.display_label || edge.parent_label;
    const derivedLabel = derived.display_label || edge.derived_label;
    const change = [edge.from_group, edge.to_group].filter((value) => value && value !== MISSING_VALUE).join(' → ') || MISSING_VALUE;
    const pairState = edge.pair_eligible ? 'PAIR READY' : 'PARENT UNRESOLVED';
    return `<div class="lineage-edge ${edge.pair_eligible ? 'is-pair-ready' : 'is-unresolved'}"><div class="lineage-depth"><span>ITERATION</span><strong>${formatNumber(edge.iteration_depth)}</strong></div><div class="lineage-compound"><span>DIRECT PARENT</span><strong>${escapeHtml(displayValue(parentLabel))}</strong><small>${escapeHtml(displayValue(parent.structure_status))}</small></div><span class="lineage-arrow">→</span><div class="lineage-compound"><span>DERIVED COMPOUND</span><strong>${escapeHtml(displayValue(derivedLabel))}</strong><small>${escapeHtml(activityText(edge.derived_activities))}</small></div><div class="lineage-modification"><span>${escapeHtml(displayValue(edge.modification_site))}</span><strong>${escapeHtml(change)}</strong><small>${escapeHtml(displayValue(edge.relation_type))}</small></div><div class="lineage-edge-state"><span class="status-tag ${edge.pair_eligible ? 'review-in_review' : 'review-needs_follow_up'}">${escapeHtml(pairState)}</span><small>${escapeHtml(displayValue(edge.relation_status))} · ${escapeHtml(displayValue(edge.relation_confidence))}</small></div></div>`;
  };
  const lanes = lineages.map((lineage, index) => {
    const root = lineage.root_template || {};
    const rootImage = root.structure_image_url
      ? `<img src="${escapeHtml(root.structure_image_url)}" alt="${escapeHtml(displayValue(root.display_label, 'root template'))} structure rendered from SMILES" />`
      : '<div class="lineage-root-placeholder">--</div>';
    return `<article class="lineage-lane"><header class="lineage-root"><div class="lineage-root-index">LINEAGE ${String(index + 1).padStart(2, '0')}</div><div class="lineage-root-visual">${rootImage}</div><div class="lineage-root-copy"><span>ROOT TEMPLATE</span><h4>${escapeHtml(displayValue(root.display_label))}</h4><p>${escapeHtml(displayValue(root.entity_origin))} · ${escapeHtml(displayValue(root.structure_review_status))}</p><code>${escapeHtml(displayValue(root.canonical_smiles))}</code></div><div class="lineage-root-counts"><div><strong>${formatNumber(lineage.edge_count)}</strong><span>DIRECT EDGES</span></div><div><strong>${formatNumber(lineage.pair_eligible_count)}</strong><span>PAIR READY</span></div><div><strong>${formatNumber(lineage.unresolved_edge_count)}</strong><span>UNRESOLVED</span></div></div></header><div class="lineage-edge-list">${lineage.edges.map(edgeRow).join('')}</div></article>`;
  }).join('');
  return `<section class="detail-section compound-lineage-section" id="compound-lineage-section"><div class="section-heading"><div><p class="section-label">COMPOUND OPTIMIZATION LINEAGE</p><h3>修改迭代链</h3></div><span class="section-count">${formatNumber(lineages.length)} lineages · ${formatNumber(edgeCount)} edges</span></div><div class="lineage-legend"><span><i class="is-ready"></i>关系明确且完整结构就绪</span><span><i class="is-unresolved"></i>直接母体尚待确认</span></div><div class="lineage-list">${lanes}</div></section>`;
}

function renderPaperObjects(detail) {
  const excludedTypes = new Set(['non_structure_region', 'three_d_structure_evidence']);
  const typeLabels = {
    complete_molecule: '完整分子', molecule_series_member: '编号分子', shared_scaffold: '共享骨架',
    replacement_fragment: '替换片段', linker_fragment: 'Linker 片段', variable_site: '可变位点',
    mixed_structure_evidence: '混合结构证据', mixed_region_molecule: '混合区域中的分子',
  };
  const objects = Array.isArray(detail?.molecule_objects)
    ? detail.molecule_objects.filter((item) => item && !excludedTypes.has(item.object_type))
    : [];
  if (!objects.length) {
    return '<section class="detail-section paper-objects-section" id="paper-objects-section"><div class="section-heading"><div><p class="section-label">STRUCTURE OBJECTS</p><h3>结构图对象</h3></div><span class="section-count">0 objects</span></div><div class="empty-state">当前 Paper 没有完成初步结构过滤的对象。</div></section>';
  }
  const typeCounts = objects.reduce((counts, item) => {
    const type = item.object_type || 'unknown';
    counts[type] = (counts[type] || 0) + 1;
    return counts;
  }, {});
  const legend = Object.entries(typeCounts).map(([type, count]) => `<span class="paper-object-legend-item molecule-type-${escapeHtml(type)}">${escapeHtml(typeLabels[type] || displayValue(type))} ${formatNumber(count)}</span>`).join('');
  const cards = objects.map((item) => {
    const label = displayValue(item.compound_label, '未编号');
    const type = typeLabels[item.object_type] || displayValue(item.object_type);
    const image = item.crop_url
      ? `<a class="paper-object-image-link" href="${escapeHtml(item.crop_url)}" target="_blank" rel="noreferrer"><img src="${escapeHtml(item.crop_url)}" alt="${escapeHtml(type)} ${escapeHtml(label)}" /></a>`
      : '<div class="paper-object-image-missing">--</div>';
    return `<article class="paper-object-card"><div class="paper-object-image">${image}</div><div class="paper-object-caption"><strong>${escapeHtml(label)}</strong><span class="fragment-scope-tag molecule-type-${escapeHtml(item.object_type || 'unknown')}">${escapeHtml(type)}</span><small>p. ${escapeHtml(displayValue(item.page))} · ${escapeHtml(displayValue(item.object_id))}</small></div></article>`;
  }).join('');
  return `<section class="detail-section paper-objects-section" id="paper-objects-section"><div class="section-heading"><div><p class="section-label">STRUCTURE OBJECTS</p><h3>初步过滤后的结构图对象</h3></div><span class="section-count">${formatNumber(objects.length)} objects · filtered</span></div><p class="section-intro">这里只显示已定位到化学结构或结构片段的图片对象；图表、文字、蛋白场景和 3D-only 区域不会进入本栏。</p><div class="paper-object-legend">${legend}</div><div class="paper-object-grid">${cards}</div></section>`;
}

function renderPaperDetail() {
  const detail = state.paperDetail;
  if (!detail) return;
  const paper = detail.paper;
  const counts = paper.detail_counts;
  const canEditEntries = state.mode === 'edit' && paper.review_status !== 'reviewed';
  const addEntry = canEditEntries ? renderAddReviewItemForm() : '';
  $('#paperDetailWorkspace').innerHTML = `<div class="detail-toolbar"><button class="back-button" data-back-papers type="button">← <span>返回 Paper 库</span></button><span class="detail-toolbar-id">${escapeHtml(paper.paper_id)}</span><span class="status-tag review-${escapeHtml(paper.review_status)}">${escapeHtml(paperReviewLabel(paper.review_status))}</span></div><div class="detail-heading"><div><p class="eyebrow">PAPER WORKSPACE / ${escapeHtml(displayValue(paper.year, 'YEAR UNKNOWN'))}</p><h2>${escapeHtml(displayValue(paper.title, 'Untitled paper'))}</h2><p class="detail-doi">${escapeHtml(displayValue(paper.doi, 'DOI unavailable'))}</p></div><div class="detail-source-box"><span>SOURCE FOLDER</span><strong>${escapeHtml(displayValue(paper.source_folder))}</strong><small>${escapeHtml(displayValue(paper.filename || paper.source_pdf))}</small></div></div><div class="paper-detail-summary"><div><span>PAPER ID</span><strong>${escapeHtml(displayValue(paper.paper_id))}</strong></div><div><span>PAGE COUNT</span><strong>${formatNumber(paper.page_count)}</strong></div><div><span>TEXT STATUS</span><strong>${escapeHtml(displayValue(paper.text_status))}</strong></div><div><span>EVIDENCE</span><strong>${formatNumber(counts.evidence)}</strong></div><div><span>REVIEW ITEMS</span><strong>${formatNumber(counts.review_items)}</strong></div><div><span>LINEAGES</span><strong>${formatNumber(counts.lineages)}</strong></div></div><section class="detail-progress panel"><div class="section-heading"><div><p class="section-label">PROCESSING PROGRESS</p><h3>这篇 Paper 目前处理到哪里</h3></div><span class="progress-note">${formatNumber(counts.review_items)} unified review entries</span></div>${renderProgress(paper.progress)}</section><nav class="detail-tabs" aria-label="Paper 内容导航"><button type="button" data-detail-anchor="paper-overview">Paper 概览</button><button type="button" data-detail-anchor="compound-lineage-section">修改迭代链 <strong>${formatNumber(counts.lineage_edges)}</strong></button><button type="button" data-detail-anchor="paper-objects-section">Objects <strong>${formatNumber(counts.molecule_objects)}</strong></button><button type="button" data-detail-anchor="review-items-section">统一复核条目 <strong>${formatNumber(counts.review_items)}</strong></button><button type="button" data-detail-anchor="paper-review-section">Paper 审阅</button></nav><section class="detail-section" id="paper-overview"><div class="section-heading"><div><p class="section-label">PAPER OVERVIEW</p><h3>来源与基础文本</h3></div></div><div class="overview-facts"><div><span>ORIGINAL TITLE</span><p>${escapeHtml(displayValue(paper.title_original || paper.title))}</p></div><div><span>DOI</span><p>${escapeHtml(displayValue(paper.doi, 'Unavailable'))}</p></div><div><span>TEXT CHARACTERS</span><p>${formatNumber(paper.text_characters)}</p></div><div><span>SOURCE PDF</span><p class="mono-value">${escapeHtml(displayValue(paper.source_pdf || paper.filename, 'Unavailable'))}</p></div></div></section>${renderCompoundLineages(detail)}${renderPaperObjects(detail)}<section class="detail-section unified-review-section" id="review-items-section"><div class="section-heading"><div><p class="section-label">UNIFIED REVIEW ITEMS</p><h3>Evidence、候选记录、路径与结构</h3></div><div class="section-heading-actions"><span class="section-count">${formatNumber(counts.review_items)} entries · activity included</span>${canEditEntries ? '<span class="edit-mode-marker">EDITABLE</span>' : ''}</div></div><p class="section-intro">每个条目集中显示可用证据；缺失信息统一显示为 <code>--</code>。结构主图来自 SI SMILES / RDKit，文章截图只作为来源证据。</p>${addEntry}${renderReviewItems(detail.review_items)}</section><section class="detail-section" id="paper-review-section"><div class="section-heading"><div><p class="section-label">PAPER REVIEW</p><h3>Paper 级审阅与修改</h3></div><span class="section-count">${escapeHtml(paperReviewLabel(paper.review_status))}</span></div>${renderPaperReview(detail)}</section>`;
  $$('#paperDetailWorkspace [data-detail-anchor]').forEach((button) => button.addEventListener('click', () => document.getElementById(button.dataset.detailAnchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })));
  const back = $('#paperDetailWorkspace [data-back-papers]');
  if (back) back.addEventListener('click', () => setView('papers'));
  const form = $('#paperEditForm');
  if (form) form.addEventListener('submit', savePaperReview);
  const cancel = $('#cancelPaperEdit');
  if (cancel) cancel.addEventListener('click', () => renderPaperDetail());
  const restore = $('#restorePaperEdit');
  if (restore) restore.addEventListener('click', () => { $('#paperTitleEdit').value = paper.title_original || ''; $('#paperReviewStatusEdit').value = 'unreviewed'; $('#paperCorrectionEdit').value = ''; $('#paperNoteEdit').value = ''; showToast('已恢复为原始值，保存后才会写入'); });
  $$('[data-save-item]').forEach((button) => button.addEventListener('click', () => saveReviewItem(button.dataset.saveItem, button)));
  $$('[data-confirm-item]').forEach((button) => button.addEventListener('click', () => confirmReviewItem(button.dataset.confirmItem, button)));
  $$('[data-delete-item]').forEach((button) => button.addEventListener('click', () => deleteReviewItem(button.dataset.deleteItem, button)));
  const addToggle = $('[data-toggle-add-entry]');
  const addForm = $('#addReviewItemForm');
  if (addToggle && addForm) {
    addToggle.addEventListener('click', () => {
      addForm.hidden = !addForm.hidden;
      addToggle.textContent = addForm.hidden ? '+ 新增复核条目' : '− 收起新增条目';
      if (!addForm.hidden) addForm.querySelector('[data-entry-field="page"]')?.focus();
    });
    addForm.addEventListener('submit', addReviewItem);
    addForm.querySelector('[data-cancel-add-entry]')?.addEventListener('click', () => { addForm.reset(); addForm.hidden = true; addToggle.textContent = '+ 新增复核条目'; });
  }
}

async function savePaperReview(event) {
  event.preventDefault();
  const payload = { review_status: $('#paperReviewStatusEdit').value, title_override: $('#paperTitleEdit').value.trim(), correction_note: $('#paperCorrectionEdit').value.trim(), review_note: $('#paperNoteEdit').value.trim() };
  try { $('#syncLabel').textContent = 'SAVING REVIEW'; state.paperDetail = await postJSON(`/api/papers/${encodeURIComponent(state.selectedPaperId)}/review`, payload); renderPaperDetail(); if (state.papers) await loadPapers(); $('#syncLabel').textContent = 'SNAPSHOT READY'; showToast('Paper 审阅修改已保存'); } catch (error) { $('#syncLabel').textContent = 'SNAPSHOT ERROR'; showToast(error.message); }
}

async function saveReviewItem(itemId, trigger) {
  const article = $(`[data-review-item="${CSS.escape(itemId)}"]`);
  if (!article) return;
  try {
    trigger.disabled = true;
    $('#syncLabel').textContent = 'SAVING ENTRY';
    state.paperDetail = await postJSON(`/api/papers/${encodeURIComponent(state.selectedPaperId)}/review-items/${encodeURIComponent(itemId)}`, readEntryPayload(article));
    renderPaperDetail();
    $('#syncLabel').textContent = 'SNAPSHOT READY';
    showToast('条目草稿已保存');
  } catch (error) { $('#syncLabel').textContent = 'SNAPSHOT ERROR'; showToast(error.message); }
}

async function confirmReviewItem(itemId, trigger) {
  const article = $(`[data-review-item="${CSS.escape(itemId)}"]`);
  if (!article || !window.confirm('确认该条目并同步到 reviewed_entries.csv？确认后将不可再编辑或删除。')) return;
  try {
    trigger.disabled = true;
    $('#syncLabel').textContent = 'SYNCING ENTRY';
    const payload = readEntryPayload(article);
    payload.review_status = payload.review_status === 'reviewed' ? 'in_review' : payload.review_status;
    await postJSON(`/api/papers/${encodeURIComponent(state.selectedPaperId)}/review-items/${encodeURIComponent(itemId)}`, payload);
    await postJSON(`/api/papers/${encodeURIComponent(state.selectedPaperId)}/review-items/${encodeURIComponent(itemId)}/confirm`);
    state.paperDetail = await getJSON(`/api/papers/${encodeURIComponent(state.selectedPaperId)}`);
    renderPaperDetail();
    if (state.papers) await loadPapers();
    $('#syncLabel').textContent = 'SNAPSHOT READY';
    showToast('条目已确认并同步');
  } catch (error) { $('#syncLabel').textContent = 'SNAPSHOT ERROR'; showToast(error.message); }
}

async function deleteReviewItem(itemId, trigger) {
  if (!window.confirm('删除该复核条目？原始抽取数据不会被修改。')) return;
  try {
    trigger.disabled = true;
    $('#syncLabel').textContent = 'DELETING ENTRY';
    state.paperDetail = await deleteJSON(`/api/papers/${encodeURIComponent(state.selectedPaperId)}/review-items/${encodeURIComponent(itemId)}`);
    renderPaperDetail();
    $('#syncLabel').textContent = 'SNAPSHOT READY';
    showToast('条目已删除');
  } catch (error) { $('#syncLabel').textContent = 'SNAPSHOT ERROR'; showToast(error.message); }
}

async function addReviewItem(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const submit = form.querySelector('button[type="submit"]');
  try {
    submit.disabled = true;
    $('#syncLabel').textContent = 'ADDING ENTRY';
    state.paperDetail = await postJSON(`/api/papers/${encodeURIComponent(state.selectedPaperId)}/review-items`, readEntryPayload(form, 'add'));
    renderPaperDetail();
    document.getElementById('review-items-section')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    $('#syncLabel').textContent = 'SNAPSHOT READY';
    showToast('新条目已添加');
  } catch (error) { submit.disabled = false; $('#syncLabel').textContent = 'SNAPSHOT ERROR'; showToast(error.message); }
}

function navigateToPapers(filter) { $('#paperStatusFilter').value = ['text_ready', 'evidence_review', 'candidate_review', 'path_review', 'lineage'].includes(filter) ? filter : 'all'; $('#paperReviewFilter').value = ['unreviewed', 'in_review', 'needs_follow_up', 'reviewed'].includes(filter) ? filter : 'all'; state.paperPage = 1; setView('papers'); }

function setView(view) { if (view === 'paper-detail' && !state.selectedPaperId) view = 'papers'; $$('.nav-item').forEach((button) => button.classList.toggle('is-active', button.dataset.view === (view === 'paper-detail' ? 'papers' : view))); $$('[data-view-panel]').forEach((panel) => panel.classList.toggle('is-active', panel.dataset.viewPanel === view)); $('#viewCrumb').textContent = viewLabels[view] || viewLabels.overview; if (view === 'papers') loadPapers(); window.scrollTo({ top: 0, behavior: 'smooth' }); }

function setMode(mode) { state.mode = mode === 'edit' ? 'edit' : 'read'; $$('.mode-button').forEach((button) => button.classList.toggle('is-active', button.dataset.mode === state.mode)); $('#modeLabel').innerHTML = `<span class="lock-dot"></span> ${state.mode === 'edit' ? 'EDIT MODE' : 'READ MODE'}`; if (state.paperDetail) renderPaperDetail(); showToast(state.mode === 'edit' ? '修改模式已开启：可审阅未完成条目' : '阅读模式已开启：数据只读'); }

function wireEvents() {
  $$('.nav-item').forEach((button) => button.addEventListener('click', () => setView(button.dataset.view)));
  $$('.mode-button').forEach((button) => button.addEventListener('click', () => setMode(button.dataset.mode)));
  $('#refreshButton').addEventListener('click', async () => { $('#syncLabel').textContent = 'REFRESHING'; try { await loadOverview(); if ($('#papersView').classList.contains('is-active')) await loadPapers(); if ($('#paperDetailView').classList.contains('is-active') && state.selectedPaperId) { state.paperDetail = await getJSON(`/api/papers/${encodeURIComponent(state.selectedPaperId)}`); renderPaperDetail(); } showToast('Snapshot refreshed'); } catch (error) { $('#syncLabel').textContent = 'SNAPSHOT ERROR'; showToast(error.message); } });
  $('#paperSearch').addEventListener('input', debounce(() => { state.paperPage = 1; loadPapers(); }, 260));
  $('#paperStatusFilter').addEventListener('change', () => { state.paperPage = 1; loadPapers(); });
  $('#paperReviewFilter').addEventListener('change', () => { state.paperPage = 1; loadPapers(); });
}

function debounce(callback, wait) { let timer; return (...args) => { window.clearTimeout(timer); timer = window.setTimeout(() => callback(...args), wait); }; }

async function boot() { wireEvents(); try { await loadOverview(); } catch (error) { $('#metricGrid').innerHTML = `<div class="error-box" style="grid-column: 1 / -1;">${escapeHtml(error.message)}</div>`; $('#syncLabel').textContent = 'SNAPSHOT ERROR'; } }

boot();
