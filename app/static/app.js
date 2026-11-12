const byId = (id) => document.getElementById(id);
const titles = { research: 'Policy research', corpus: 'Source corpus', trace: 'Execution trace' };
let lastReceipt = null;
let source = null;
let imageUrl = null;

function node(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function showView(view) {
  for (const name of Object.keys(titles)) byId(`${name}-view`).hidden = name !== view;
  for (const button of document.querySelectorAll('[data-view]')) {
    const active = button.dataset.view === view;
    button.classList.toggle('active', active);
    if (active) button.setAttribute('aria-current', 'page');
    else button.removeAttribute('aria-current');
  }
  byId('page-title').textContent = titles[view];
}

async function openSource(item) {
  byId('source-title').textContent = item.title;
  source = { docId: item.doc_id, page: item.page_number || 1, total: 0 };
  byId('source-download').href = `/api/documents/${encodeURIComponent(item.doc_id)}#page=${source.page}`;
  byId('source-dialog').showModal();
  await loadSourcePage();
}

async function loadSourcePage() {
  const requested = { ...source };
  byId('source-image').hidden = true;
  byId('source-loading').hidden = false;
  byId('source-loading').textContent = 'Rendering source page.';
  byId('previous-page').disabled = true;
  byId('next-page').disabled = true;
  try {
    const response = await fetch(`/api/documents/${encodeURIComponent(requested.docId)}/preview/${requested.page}`);
    if (!response.ok) throw new Error('Source page is unavailable or access was denied.');
    const blob = await response.blob();
    if (!source || source.docId !== requested.docId || source.page !== requested.page) return;
    source.total = Number(response.headers.get('X-Page-Count'));
    if (imageUrl) URL.revokeObjectURL(imageUrl);
    imageUrl = URL.createObjectURL(blob);
    byId('source-image').src = imageUrl;
    byId('source-image').alt = `${byId('source-title').textContent}, page ${source.page}`;
    byId('source-image').hidden = false;
    byId('source-loading').hidden = true;
    byId('source-page').textContent = `PAGE ${source.page} / ${source.total}`;
    byId('previous-page').disabled = source.page <= 1;
    byId('next-page').disabled = source.page >= source.total;
  } catch (error) {
    byId('source-loading').textContent = error.message;
  }
}

function renderEvidence(items) {
  const list = byId('evidence-list');
  list.replaceChildren();
  byId('evidence-count').textContent = items.length;
  if (!items.length) list.append(node('div', 'empty-state', 'No authorized passages matched.'));
  for (const item of items) {
    const article = node('article', 'evidence-item');
    const top = node('div', 'evidence-top');
    top.append(node('span', 'evidence-id', item.evidence_id), node('span', '', item.classification.toUpperCase()));
    const bottom = node('div', 'evidence-bottom');
    const button = node('button', 'text-button', 'Open source \u2197');
    button.type = 'button';
    button.addEventListener('click', () => openSource(item));
    bottom.append(node('span', '', `PAGE ${item.page_number} / V${item.document_version}`), button);
    article.append(top, node('h3', '', item.title), node('p', 'evidence-text', item.text), bottom);
    list.append(article);
  }
}

function renderTrace(result) {
  lastReceipt = result;
  byId('download-receipt').disabled = false;
  byId('trace-request').textContent = result.request_id.slice(0, 8).toUpperCase();
  const events = byId('trace-events');
  events.replaceChildren();
  for (const event of result.trace) {
    const row = node('article', 'trace-event');
    const heading = node('h3');
    heading.append(node('span', '', event.stage), node('span', '', `${event.milliseconds} ms`));
    row.append(heading, node('p', '', event.detail));
    if (event.filters) row.append(node('p', '', JSON.stringify(event.filters)));
    events.append(row);
  }
  byId('raw-response').textContent = JSON.stringify({
    request_id: result.request_id, mode: result.mode, elapsed_ms: result.elapsed_ms,
    filters: result.filters, citations: result.citations, trace: result.trace,
    evidence: result.evidence.map(({ chunk_id, doc_id, page_number, score }) => ({ chunk_id, doc_id, page_number, score })),
  }, null, 2);
}

async function loadStatus() {
  const response = await fetch('/api/status');
  if (!response.ok) throw new Error('Cannot read application status.');
  const status = await response.json();
  const live = status.mode !== 'offline';
  const labels = { offline: 'OFFLINE REHEARSAL', databricks: 'DATABRICKS RETRIEVAL', foundry: 'LIVE CONFIGURED' };
  byId('mode').textContent = live && status.last_live_success ? 'LIVE VERIFIED' : labels[status.mode] || 'INVALID CONFIGURATION';
  byId('mode').classList.toggle('live', live && Boolean(status.last_live_success));
  byId('doc-count').textContent = status.documents;
  byId('tenant').textContent = status.tenant;
  byId('groups').textContent = status.groups.join(', ');
  byId('notice').textContent = status.configuration_error || (live
    ? 'Cloud mode configured. Verification requires a successful request; no offline fallback.'
    : 'OFFLINE / Local PDF retrieval. Databricks and Foundry have not been called.');
  byId('notice').classList.toggle('live', live && Boolean(status.last_live_success));
  byId('footer-status').textContent = status.mode === 'offline' ? 'Local BM25 / No model call' : `${status.mode.toUpperCase()} / Azure CLI identity`;
  byId('public-count').textContent = `${status.public_documents} PUBLIC REPORTS`;
  byId('pipeline-list').replaceChildren(...status.pipeline.map((stage) => {
    const item = node('li', ['ready', 'verified'].includes(stage.state) ? 'ready' : '', stage.name);
    item.append(node('small', '', stage.state.toUpperCase()));
    return item;
  }));
}

async function loadCorpus() {
  const response = await fetch('/api/documents');
  if (!response.ok) throw new Error('Cannot read source documents.');
  const documents = await response.json();
  byId('nav-count').textContent = documents.length;
  const table = byId('corpus-table');
  table.replaceChildren();
  for (const item of documents) {
    const row = node('tr');
    row.append(node('td', '', item.title), node('td', '', item.source_url ? 'BIS publication' : 'Synthetic bank policy'), node('td', '', item.document_version), node('td', '', item.effective_date));
    const action = node('td');
    const button = node('button', 'text-button', 'Open PDF \u2197');
    button.type = 'button';
    button.addEventListener('click', () => openSource(item));
    action.append(button);
    row.append(action);
    table.append(row);
  }
}

for (const button of document.querySelectorAll('[data-view]')) button.addEventListener('click', () => showView(button.dataset.view));
for (const button of document.querySelectorAll('[data-question]')) button.addEventListener('click', () => {
  byId('question').value = button.dataset.question;
  byId('question').focus();
});
byId('trace-shortcut').addEventListener('click', () => showView('trace'));
byId('close-source').addEventListener('click', () => {
  byId('source-dialog').close();
  source = null;
  byId('source-image').removeAttribute('src');
  if (imageUrl) URL.revokeObjectURL(imageUrl);
  imageUrl = null;
});
byId('previous-page').addEventListener('click', () => { if (source && source.page > 1) { source.page--; loadSourcePage(); } });
byId('next-page').addEventListener('click', () => { if (source && source.page < source.total) { source.page++; loadSourcePage(); } });
byId('download-receipt').addEventListener('click', () => {
  if (!lastReceipt) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(lastReceipt, null, 2)], { type: 'application/json' }));
  const anchor = node('a');
  anchor.href = url;
  anchor.download = `rag-receipt-${lastReceipt.request_id}.json`;
  anchor.click();
  URL.revokeObjectURL(url);
});
byId('as-of').value = new Date().toISOString().slice(0, 10);
byId('question-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  byId('submit').disabled = true;
  byId('submit').textContent = 'Researching...';
  byId('error').hidden = true;
  byId('answer-meta').textContent = 'REQUEST IN PROGRESS';
  try {
    const response = await fetch('/api/ask', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: byId('question').value, as_of: byId('as-of').value, top_k: 6 }),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : 'The request was rejected. Check the question and date.');
    byId('answer').textContent = result.answer;
    byId('answer-meta').textContent = `${result.elapsed_ms} MS / ${result.mode.toUpperCase()}`;
    byId('citation-summary').replaceChildren(...result.citations.map((citation) => node('span', '', citation)));
    renderEvidence(result.evidence);
    renderTrace(result);
    await loadStatus();
  } catch (error) {
    byId('error').textContent = error.message;
    byId('error').hidden = false;
    byId('answer-meta').textContent = 'REQUEST FAILED';
  } finally {
    byId('submit').disabled = false;
    byId('submit').textContent = 'Run research \u2192';
  }
});
Promise.all([loadStatus(), loadCorpus()]).catch((error) => {
  byId('notice').textContent = error.message;
});