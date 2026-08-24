const state = { data: null };

const formatTime = (iso, options = {}) => new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Los_Angeles',
  month: 'short',
  day: 'numeric',
  hour: 'numeric',
  minute: '2-digit',
  ...options
}).format(new Date(iso));

const formatClock = (iso) => new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Los_Angeles',
  hour: 'numeric',
  minute: '2-digit'
}).format(new Date(iso));

const formatDay = (iso) => new Intl.DateTimeFormat('en-US', {
  timeZone: 'America/Los_Angeles',
  month: 'short',
  day: 'numeric'
}).format(new Date(iso));

const statusCopy = (status) => status === 'available' ? 'Available' : 'Unavailable';
const ticketCountCopy = (status) => status === 'available' ? 'Tickets Available' : '0 Tickets Available';

const escapeHtml = (value) => String(value)
  .replaceAll('&', '&amp;')
  .replaceAll('<', '&lt;')
  .replaceAll('>', '&gt;')
  .replaceAll('"', '&quot;')
  .replaceAll("'", '&#039;');

const cleanEvidenceLine = (line) => line
  .replace(/\b(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\1\b/gi, '$1')
  .replace(/\s+UNAVAILABLE\s+HYROX\s+(.+)$/i, (_, division) => {
    const titleCaseDivision = division.toLowerCase().replace(/\b\w/g, (letter) => letter.toUpperCase());
    return ` — HYROX ${titleCaseDivision}`;
  });

const formatEvidence = (evidence, fallbackStatus) => {
  const rawLines = evidence.split(/\s*\|\s*/);
  const dates = [];
  const metadata = [];
  let offeringHeading = '';
  let pendingStatus = fallbackStatus;

  rawLines.forEach((rawLine) => {
    const line = cleanEvidenceLine(rawLine);
    if (/\bUNAVAILABLE\b/i.test(rawLine)) pendingStatus = 'unavailable';
    else if (/\bAVAILABLE\b/i.test(rawLine)) pendingStatus = 'available';

    if (line.includes(' — HYROX ')) {
      if (!offeringHeading) offeringHeading = line;
      return;
    }
    if (/^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\b/i.test(line)) {
      dates.push({ date: line, status: pendingStatus });
      return;
    }
    if (/\s+(UNAVAILABLE|AVAILABLE)$/i.test(rawLine)) return;
    if (!metadata.includes(line)) metadata.push(line);
  });

  const dateSections = dates.map(({ date, status }, index) => `
    <section class="${index ? 'mt-4' : 'mt-2'}">
      <h3 class="border-l-2 border-cyan bg-cyan/[.08] px-2 py-1.5 text-[11px] font-black uppercase tracking-[.12em] text-white">${escapeHtml(date)}</h3>
      <p class="flex items-center gap-2 border-b border-line/50 px-2 py-2 font-bold ${status === 'available' ? 'text-lime' : 'text-coral'}">
        <span class="h-2 w-2 rounded-full ${status === 'available' ? 'bg-lime' : 'bg-coral'}"></span>${status === 'available' ? 'Tickets available' : '0 tickets available'}
      </p>
    </section>`).join('');

  const metadataSection = metadata.length
    ? metadata.map((line) => `<p class="mt-1.5 first:mt-0 leading-5 text-slate-200">${escapeHtml(line)}</p>`).join('')
    : '<p class="text-gray-300">No additional event information recorded.</p>';

  const notesSection = `
    <section class="mt-4 border-t-2 border-line pt-3">
      <h3 class="text-[11px] font-black uppercase tracking-[.12em] text-gray-300">Notes</h3>
      ${offeringHeading ? `<p class="mt-2 font-bold text-white">${escapeHtml(offeringHeading)}</p>` : ''}
      ${dateSections}
    </section>`;

  return `${metadataSection}${notesSection}`;
};

function summaryCard(label, value, note, tone = 'text-white', link = null) {
  return `<article class="bg-panel px-3 py-2.5">
    <p class="text-[11px] font-bold uppercase tracking-[.16em] text-gray-300">${label}</p>
    <p class="mt-1 text-xl font-black tracking-tight ${tone}">${value}</p>
    <p class="mt-0.5 truncate text-[11px] font-semibold text-gray-300">${note}${link ? ` · <a href="${link.href}" target="_blank" rel="noreferrer" class="font-bold text-gray-200 underline decoration-line underline-offset-2 transition hover:text-white focus:outline-none focus:ring-2 focus:ring-cyan/60">${link.label}</a>` : ''}</p>
  </article>`;
}

function showDetail(category, observation) {
  const ticket = observation.tickets[category];
  const title = document.querySelector('#detail-title');
  const body = document.querySelector('#detail-body');
  title.textContent = category;
  body.innerHTML = `
    <div class="mb-3 flex items-center justify-between gap-2">
      <span class="inline-flex items-center gap-2 font-bold ${ticket.status === 'available' ? 'text-lime' : 'text-coral'}">
        <span class="h-2 w-2 rounded-full ${ticket.status === 'available' ? 'bg-lime' : 'bg-coral'}"></span>${ticketCountCopy(ticket.status)}
      </span>
      <time class="text-[11px] font-bold uppercase tracking-wider text-gray-300">${formatTime(observation.checked_at)}</time>
    </div>
    <p class="mb-1 text-[11px] font-bold uppercase tracking-[.16em] text-gray-300">Event information</p>
    <div class="evidence-scroll h-44 overflow-y-scroll border-l-2 border-line pl-3 pr-2 text-xs font-semibold leading-5 text-slate-200" tabindex="0" aria-label="Notes; scroll for full text">${formatEvidence(ticket.evidence, ticket.status)}</div>`;
}

function selectCategory(category) {
  document.querySelectorAll('[data-snapshot-row]').forEach((row) => {
    row.setAttribute('aria-selected', String(row.dataset.category === category));
  });
}

function selectHistoryCell(category, checkedAt) {
  document.querySelectorAll('[data-history-cell]').forEach((cell) => {
    const isSelected = cell.dataset.category === category && cell.dataset.time === checkedAt;
    cell.setAttribute('aria-selected', String(isSelected));
  });
}

function renderSnapshot(observation, categories, meta) {
  document.querySelector('#snapshot-time').textContent = `Check · ${formatTime(observation.checked_at)}`;
  document.querySelector('#latest-list').innerHTML = categories.map((category) => {
    const ticket = observation.tickets[category];
    const openingCount = meta.openings[category].opening_transitions;
    return `<button type="button" data-snapshot-row data-category="${category}" data-time="${observation.checked_at}" aria-selected="false" class="snapshot-row grid h-full w-full grid-cols-[minmax(0,1fr)_auto_auto] items-center gap-3 px-3 py-2.5 text-left transition hover:bg-white/[.03] focus:outline-none focus:ring-2 focus:ring-inset focus:ring-cyan/60">
      <span class="truncate text-xs font-semibold text-slate-200">${category}</span>
      <span class="text-[11px] font-semibold text-gray-300">${openingCount} openings</span>
      <span class="inline-flex min-w-36 items-center justify-center gap-1.5 whitespace-nowrap border px-2 py-1 text-[11px] font-bold uppercase tracking-wider ${ticket.status === 'available' ? 'border-lime/25 bg-lime/10 text-lime' : 'border-coral/25 bg-coral/10 text-coral'}">
        <span class="h-1.5 w-1.5 rounded-full ${ticket.status === 'available' ? 'bg-lime' : 'bg-coral'}"></span>${ticketCountCopy(ticket.status)}
      </span>
    </button>`;
  }).join('');
}

function render(data) {
  state.data = data;
  const { meta, history } = data;
  const latest = history.at(-1);
  const displayHistory = [...history].reverse();
  const categories = Object.keys(latest.tickets);
  const availableNow = categories.filter((name) => latest.tickets[name].status === 'available').length;

  document.querySelector('#last-updated').textContent = `Last Check ${formatTime(latest.checked_at)}`;
  document.querySelector('#event-link').href = latest.source_url;
  document.querySelector('#range-label').textContent = `${history.length} checks · Newest first · ${formatTime(meta.window_start)}–${formatTime(meta.window_end)}`;
  document.querySelector('#summary').innerHTML = [
    summaryCard('Available now', `${availableNow}/${categories.length}`, availableNow ? 'Tickets detected' : 'All monitored tickets closed', availableNow ? 'text-lime' : 'text-coral'),
    summaryCard('Ticket openings', meta.total_openings, 'Within retained history', meta.total_openings ? 'text-lime' : 'text-white'),
    summaryCard('Checks logged', meta.observation_count, `${meta.retention_days}-day rolling window`, 'text-cyan', { href: 'https://github.com/matt22/hyrox/blob/main/state/current.json', label: 'Data Log ↗' }),
    summaryCard('Divisions tracked', categories.length, 'Selected event categories', 'text-white')
  ].join('');

  const matrix = document.querySelector('#matrix');
  matrix.style.setProperty('--checks', history.length);
  const timeHeaders = displayHistory.map((observation, index) => `
    <div class="flex min-h-14 items-end justify-center border-l border-line px-1 pb-2 text-center text-[11px] font-bold text-gray-300 ${index === displayHistory.length - 1 ? 'border-r' : ''}" title="${formatTime(observation.checked_at)}">
      <span>${index === 0 || formatDay(observation.checked_at) !== formatDay(displayHistory[index - 1].checked_at) ? formatDay(observation.checked_at) + '<br>' : ''}${formatClock(observation.checked_at)}</span>
    </div>`).join('');

  const rows = categories.map((category, categoryIndex) => {
    const alternateRow = categoryIndex % 2 === 1 ? 'bg-white/[.025]' : '';
    const cells = displayHistory.map((observation, index) => {
      const status = observation.tickets[category].status;
      return `<button type="button" data-history-cell data-category="${category}" data-time="${observation.checked_at}" aria-selected="false" class="matrix-cell relative grid min-h-11 place-items-center border-l border-t border-line transition hover:bg-white/[.05] focus:outline-none focus:ring-2 focus:ring-inset focus:ring-cyan/60 ${alternateRow} ${index === displayHistory.length - 1 ? 'border-r' : ''}" aria-label="${category}, ${statusCopy(status)}, ${formatTime(observation.checked_at)}">
        <span class="h-2.5 w-2.5 rounded-full ${status === 'available' ? 'bg-lime shadow-[0_0_8px_rgba(142,234,111,.6)]' : 'bg-coral/80'}"></span>
        <span class="matrix-tip pointer-events-none absolute bottom-full left-1/2 z-20 w-max max-w-44 -translate-x-1/2 bg-slate-950 px-2 py-1 text-[11px] font-semibold text-slate-100 opacity-0 shadow-xl transition">${statusCopy(status)} · ${formatTime(observation.checked_at)}</span>
      </button>`;
    }).join('');
    return `<div class="contents">
      <button type="button" data-category="${category}" data-time="${latest.checked_at}" class="flex min-h-11 items-center gap-2 border-t border-line px-3 text-left text-xs font-semibold text-slate-100 transition hover:bg-white/[.05] focus:outline-none focus:ring-2 focus:ring-inset focus:ring-cyan/60 ${alternateRow}">
        <span class="h-1.5 w-1.5 shrink-0 rounded-full ${latest.tickets[category].status === 'available' ? 'bg-lime' : 'bg-coral'}"></span><span class="truncate">${category}</span>
      </button>${cells}
    </div>`;
  }).join('');

  matrix.innerHTML = `<div class="matrix-grid grid">
    <div class="flex min-h-14 items-end px-3 pb-2 text-[11px] font-bold uppercase tracking-[.16em] text-gray-300">Division / check</div>
    ${timeHeaders}${rows}
  </div>`;

  renderSnapshot(latest, categories, meta);

  document.addEventListener('click', (event) => {
    const trigger = event.target.closest('[data-category][data-time]');
    if (!trigger) return;
    const observation = history.find((item) => item.checked_at === trigger.dataset.time);
    if (observation) {
      renderSnapshot(observation, categories, meta);
      selectCategory(trigger.dataset.category);
      selectHistoryCell(trigger.dataset.category, observation.checked_at);
      showDetail(trigger.dataset.category, observation);
    }
  });
  selectCategory(categories[0]);
  selectHistoryCell(categories[0], latest.checked_at);
  showDetail(categories[0], latest);
}

fetch('state/current.json', { cache: 'no-store' })
  .then((response) => {
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  })
  .then(render)
  .catch((error) => {
    document.querySelector('#last-updated').textContent = 'Data unavailable';
    document.querySelector('#summary').innerHTML = `<div class="col-span-full bg-panel p-4 text-sm text-coral">Could not load state/current.json (${error.message}). Serve this repository through a local web server.</div>`;
  });

function closePopovers(exceptId = null) {
  document.querySelectorAll('[data-popover-trigger]').forEach((trigger) => {
    const id = trigger.dataset.popoverTrigger;
    if (id === exceptId) return;
    const popover = document.getElementById(id);
    popover.classList.add('hidden', 'pointer-events-none');
    trigger.setAttribute('aria-expanded', 'false');
  });
}

document.addEventListener('click', (event) => {
  const trigger = event.target.closest('[data-popover-trigger]');
  if (trigger) {
    const id = trigger.dataset.popoverTrigger;
    const popover = document.getElementById(id);
    const willOpen = popover.classList.contains('hidden');
    closePopovers(id);
    popover.classList.toggle('hidden', !willOpen);
    popover.classList.toggle('pointer-events-none', !willOpen);
    trigger.setAttribute('aria-expanded', String(willOpen));
    return;
  }
  if (!event.target.closest('.popover')) closePopovers();
});

document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closePopovers();
});
