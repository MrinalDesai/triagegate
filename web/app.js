/* TriageGate — shared utilities */

/** Highlight a <pre> block with simple diff colouring */
function renderDiff(pre, text) {
  const lines = text.split('\n');
  pre.innerHTML = lines.map(line => {
    if (line.startsWith('+')) return `<span class="diff-add">${esc(line)}</span>`;
    if (line.startsWith('-')) return `<span class="diff-del">${esc(line)}</span>`;
    if (line.startsWith('@@') || line.startsWith('diff') || line.startsWith('index') || line.startsWith('---') || line.startsWith('+++'))
      return `<span class="diff-meta">${esc(line)}</span>`;
    return esc(line);
  }).join('\n');
}

function esc(s) {
  return s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

/** Mark current nav link as active based on current page filename */
function markActiveNav() {
  const page = location.pathname.split('/').pop() || 'index.html';
  document.querySelectorAll('nav a').forEach(a => {
    const href = a.getAttribute('href');
    if (href === page || (page === '' && href === 'index.html')) {
      a.classList.add('active');
    }
  });
}

document.addEventListener('DOMContentLoaded', markActiveNav);
