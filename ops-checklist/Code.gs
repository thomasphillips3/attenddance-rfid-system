/**
 * Fall Go-Live Checklist — Apps Script backend.
 * Paste this into Extensions → Apps Script on the checklist Google Sheet,
 * then Deploy → New deployment → Web app → Execute as: Me →
 * Who has access: Anyone → Deploy. Copy the resulting /exec URL into
 * index.html's API_BASE constant.
 *
 * Sheet must have a tab named "Checklist" with header row:
 * item_id | sort_order | title | note | done | done_at | updated_at
 */

const SHEET_NAME = 'Checklist';

// Canonical seed TSV, published to S3 by deploy.sh. syncContent() reads item
// copy from here so sheet-seed-data.tsv stays the single source of truth.
const SEED_URL = 'https://attenddance-checklist.s3.amazonaws.com/seed.tsv';

function _sheet() {
  return SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
}

/**
 * One-off maintenance — run from the Apps Script editor after editing
 * sheet-seed-data.tsv and re-running ./deploy.sh. Re-syncs every row's
 * sort_order / title / note from the published seed TSV WITHOUT touching
 * done / done_at, so nobody's check-off progress is lost. Appends any brand
 * new item_id; never deletes rows (remove those by hand if you ever need to).
 */
function syncContent() {
  const tsv = UrlFetchApp.fetch(SEED_URL, { muteHttpExceptions: true }).getContentText();
  const lines = tsv.split(/\r?\n/).filter(l => l.trim() !== '');
  const seedHeaders = lines[0].split('\t');
  const sIdx = seedHeaders.indexOf('item_id');
  const sortIdx = seedHeaders.indexOf('sort_order');
  const titleIdx = seedHeaders.indexOf('title');
  const noteIdx = seedHeaders.indexOf('note');

  const canonical = {};
  const order = [];
  for (let i = 1; i < lines.length; i++) {
    const cells = lines[i].split('\t');
    const id = String(cells[sIdx]);
    canonical[id] = { sort_order: cells[sortIdx], title: cells[titleIdx], note: cells[noteIdx] };
    order.push(id);
  }

  const sheet = _sheet();
  const rows = sheet.getDataRange().getValues();
  const h = rows[0];
  const idCol = h.indexOf('item_id');
  const sortCol = h.indexOf('sort_order');
  const titleCol = h.indexOf('title');
  const noteCol = h.indexOf('note');

  const seen = {};
  for (let r = 1; r < rows.length; r++) {
    const id = String(rows[r][idCol]);
    if (canonical[id]) {
      sheet.getRange(r + 1, sortCol + 1).setValue(canonical[id].sort_order);
      sheet.getRange(r + 1, titleCol + 1).setValue(canonical[id].title);
      sheet.getRange(r + 1, noteCol + 1).setValue(canonical[id].note);
      seen[id] = true;
    }
  }
  order.forEach(id => {
    if (!seen[id]) {
      const row = [];
      row[idCol] = id;
      row[sortCol] = canonical[id].sort_order;
      row[titleCol] = canonical[id].title;
      row[noteCol] = canonical[id].note;
      sheet.appendRow(row);
    }
  });
}

function _cors(output) {
  // Pass-through seam. Apps Script Web Apps don't handle OPTIONS preflight, so
  // the frontend deliberately avoids sending requests that would trigger one
  // (no custom Content-Type header), which means no CORS headers are needed
  // today. This wrapper returns the output unchanged — it's just a single
  // choke point to add Access-Control-Allow-Origin later if a frontend change
  // ever needs it. (ContentService can't set arbitrary response headers, so
  // any real CORS support would require switching to a different response type.)
  return output;
}

function doGet(e) {
  const sheet = _sheet();
  const rows = sheet.getDataRange().getValues();
  const headers = rows[0];
  const items = rows.slice(1)
    .filter(row => row.some(cell => cell !== ''))
    .map(row => {
      const obj = {};
      headers.forEach((h, i) => { obj[h] = row[i]; });
      return obj;
    })
    .sort((a, b) => a.sort_order - b.sort_order);

  return _cors(ContentService.createTextOutput(JSON.stringify({ items }))
    .setMimeType(ContentService.MimeType.JSON));
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    const body = JSON.parse(e.postData.contents);
    const itemId = String(body.item_id || '');
    if (!itemId) {
      return _cors(ContentService.createTextOutput(JSON.stringify({ error: 'item_id is required' }))
        .setMimeType(ContentService.MimeType.JSON));
    }
    const done = !!body.done;
    const now = new Date().toISOString();

    const sheet = _sheet();
    const rows = sheet.getDataRange().getValues();
    const headers = rows[0];
    const idCol = headers.indexOf('item_id');
    const doneCol = headers.indexOf('done');
    const doneAtCol = headers.indexOf('done_at');
    const updatedAtCol = headers.indexOf('updated_at');

    for (let r = 1; r < rows.length; r++) {
      if (String(rows[r][idCol]) === itemId) {
        sheet.getRange(r + 1, doneCol + 1).setValue(done);
        sheet.getRange(r + 1, doneAtCol + 1).setValue(done ? now : '');
        sheet.getRange(r + 1, updatedAtCol + 1).setValue(now);
        break;
      }
    }
    return _cors(ContentService.createTextOutput(JSON.stringify({ ok: true }))
      .setMimeType(ContentService.MimeType.JSON));
  } finally {
    lock.releaseLock();
  }
}
