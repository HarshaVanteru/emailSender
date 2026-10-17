import DOMPurify from 'dompurify';

export function textToHtml(text: string): string {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;').replaceAll("'", '&#39;').replaceAll('\n', '<br>');
}

export function sanitizeComposeHtml(value: string): string {
  const clean = DOMPurify.sanitize(value, {
    ALLOWED_TAGS: ['p', 'div', 'br', 'span', 'b', 'strong', 'i', 'em', 'u', 's', 'strike', 'blockquote', 'pre', 'code', 'ul', 'ol', 'li', 'h1', 'h2', 'h3', 'a', 'img', 'font', 'hr'],
    ALLOWED_ATTR: ['href', 'src', 'alt', 'width', 'height', 'style', 'color', 'face', 'size', 'align'],
  });
  const template = document.createElement('template');
  template.innerHTML = clean;
  for (const image of template.content.querySelectorAll('img')) {
    if (!/^data:image\/(png|jpeg|gif|webp);base64,[A-Za-z0-9+/=]+$/.test(image.getAttribute('src') || '')) image.remove();
    else image.style.maxWidth = '100%';
  }
  const allowedStyles = new Set(['color', 'background-color', 'font-family', 'font-size', 'font-weight', 'font-style', 'text-decoration', 'text-align', 'margin-left']);
  for (const element of template.content.querySelectorAll<HTMLElement>('[style]')) {
    for (const property of Array.from(element.style)) {
      if (!allowedStyles.has(property) && !(element.tagName === 'IMG' && property === 'max-width')) element.style.removeProperty(property);
    }
  }
  for (const link of template.content.querySelectorAll('a')) {
    if (!/^(https?:\/\/|mailto:)/i.test(link.getAttribute('href') || '')) link.removeAttribute('href');
    link.setAttribute('target', '_blank'); link.setAttribute('rel', 'noopener noreferrer');
  }
  return template.innerHTML;
}

