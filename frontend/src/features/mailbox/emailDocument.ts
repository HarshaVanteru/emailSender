import purifier from 'dompurify';

// Email CSS belongs in a separate document, never in the application DOM.
const elements = ['html', 'head', 'body', 'style', 'div', 'span', 'p', 'br', 'hr',
  'b', 'strong', 'i', 'em', 'u', 's', 'del', 'ins', 'sub', 'sup', 'small', 'font',
  'center', 'blockquote', 'pre', 'code', 'ul', 'ol', 'li', 'dl', 'dt', 'dd',
  'table', 'caption', 'colgroup', 'col', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th',
  'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'a', 'img', 'section', 'article', 'header', 'footer'];
const attributes = ['style', 'class', 'id', 'dir', 'lang', 'title', 'href', 'src', 'alt',
  'width', 'height', 'align', 'valign', 'bgcolor', 'color', 'face', 'size',
  'border', 'cellpadding', 'cellspacing', 'colspan', 'rowspan', 'scope', 'start', 'type'];

export async function buildEmailDocument(html: string, showImages: boolean) {
  const clean = purifier.sanitize(html, {
    WHOLE_DOCUMENT: true, RETURN_DOM: true,
    ALLOWED_TAGS: elements, ALLOWED_ATTR: attributes,
    ALLOW_DATA_ATTR: false, ALLOW_ARIA_ATTR: false,
    FORBID_CONTENTS: ['script', 'iframe', 'object', 'embed', 'svg', 'math', 'template'],
  });
  if (!(clean instanceof HTMLElement)) throw new Error('Could not format this message.');
  clean.querySelectorAll('a').forEach(link => {
    const href = link.getAttribute('href') || '';
    if (!/^(https?:\/\/|mailto:)/i.test(href)) link.removeAttribute('href');
    else {
      link.setAttribute('target', '_blank');
      link.setAttribute('rel', 'noopener noreferrer');
    }
  });
  let hasRemoteImages = false;
  clean.querySelectorAll('img').forEach(image => {
    const src = image.getAttribute('src') || '';
    const remote = /^https:\/\//i.test(src);
    hasRemoteImages ||= remote;
    const inline = /^data:image\/(png|jpe?g|gif|webp|avif);base64,/i.test(src);
    if (!(inline || (remote && showImages))) image.removeAttribute('src');
    image.setAttribute('referrerpolicy', 'no-referrer');
  });
  hasRemoteImages ||= [...clean.querySelectorAll('style, [style]')].some(node =>
    /url\s*\(/i.test(node.tagName === 'STYLE' ? node.textContent || '' : node.getAttribute('style') || ''));

  // Install CSP before sender CSS/content to block external stylesheets/fonts,
  // scripts, forms, embedded documents, and tracking backgrounds by default.
  // Never combine allow-scripts with allow-same-origin on the iframe.
  const policy = `default-src 'none'; script-src 'none'; style-src 'unsafe-inline'; img-src data:${showImages ? ' https:' : ''}; font-src 'none'; connect-src 'none'; media-src 'none'; object-src 'none'; frame-src 'none'; base-uri 'none'; form-action 'none'`;
  const head = clean.querySelector('head')!;
  const meta = document.createElement('meta');
  meta.setAttribute('http-equiv', 'Content-Security-Policy');
  meta.setAttribute('content', policy);
  const referrer = document.createElement('meta');
  referrer.name = 'referrer'; referrer.content = 'no-referrer';
  const defaults = document.createElement('style');
  defaults.textContent = `html { color-scheme: light; background: #fff; }
    body { display: flow-root; margin: 0; padding: 12px; box-sizing: border-box; color: #202124; background: #fff; font: 14px/1.5 Arial, Helvetica, sans-serif; overflow-wrap: anywhere; }
    img { max-width: 100%; height: auto; }
    pre { white-space: pre-wrap; }
    table { max-width: 100%; }
    a { color: #1558b0; }`;
  head.prepend(meta, referrer, defaults);
  return { document: `<!doctype html>${clean.outerHTML}`, hasRemoteImages };
}
