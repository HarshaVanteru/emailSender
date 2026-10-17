import { useLayoutEffect, useRef, useState } from 'react';
import { sanitizeComposeHtml, textToHtml } from './composeHtml';
import { readFileAsBase64 } from './api';

export function RichTextEditor({ body, html, disabled, signature, onChange, onError }: {
  body: string; html?: string | null; disabled: boolean; signature: string;
  onChange: (body: string, html: string | null) => void; onError: (message: string) => void;
}) {
  const editor = useRef<HTMLDivElement>(null);
  const imageInput = useRef<HTMLInputElement>(null);
  const selection = useRef<Range | null>(null);
  const lastEmitted = useRef<{ body: string; html: string | null } | null>(null);
  const [plain, setPlain] = useState(false);
  useLayoutEffect(() => {
    if (!editor.current || plain) return;
    if (lastEmitted.current?.body === body && lastEmitted.current?.html === (html ?? null)) return;
    editor.current.innerHTML = sanitizeComposeHtml(html ?? textToHtml(body));
    lastEmitted.current = { body, html: html ?? null };
  }, [body, html, plain]);
  function rememberSelection() {
    const current = window.getSelection();
    if (current?.rangeCount && editor.current?.contains(current.anchorNode)) selection.current = current.getRangeAt(0).cloneRange();
  }
  function emit() {
    if (!editor.current) return;
    const clean = sanitizeComposeHtml(editor.current.innerHTML);
    const text = editor.current.innerText;
    lastEmitted.current = { body: text, html: clean };
    onChange(text, clean);
    rememberSelection();
  }
  function command(name: string, value?: string) {
    if (disabled || plain) return;
    editor.current?.focus();
    if (selection.current && editor.current?.contains(selection.current.commonAncestorContainer)) {
      const current = window.getSelection();
      current?.removeAllRanges(); current?.addRange(selection.current);
    }
    document.execCommand(name, false, value);
    emit();
  }
  async function insertImage(file?: File) {
    if (!file) return;
    if (!['image/png', 'image/jpeg', 'image/gif', 'image/webp'].includes(file.type) || file.size > 5 * 1024 * 1024) {
      onError('Choose a PNG, JPEG, GIF, or WebP image up to 5 MB.'); return;
    }
    try { command('insertHTML', `<img src="data:${file.type};base64,${await readFileAsBase64(file)}" alt="Inline image"><br>`); }
    catch (error) { onError(error instanceof Error ? error.message : 'Could not insert the image.'); }
    if (imageInput.current) imageInput.current.value = '';
  }
  const actions = [
    ['Bold', 'bold', 'B'], ['Italic', 'italic', 'I'], ['Underline', 'underline', 'U'],
    ['Strikethrough', 'strikeThrough', 'S'], ['Bulleted list', 'insertUnorderedList', 'Bullets'],
    ['Numbered list', 'insertOrderedList', '1. List'], ['Align left', 'justifyLeft', 'Left'],
    ['Align center', 'justifyCenter', 'Center'], ['Align right', 'justifyRight', 'Right'],
    ['Quote', 'formatBlock', 'Quote'], ['Remove formatting', 'removeFormat', 'Clear format'],
    ['Undo typing', 'undo', 'Undo'], ['Redo typing', 'redo', 'Redo'],
  ];
  return <div className="compose-rich-editor">
    <div className="compose-formatting" role="toolbar" aria-label="Message formatting">
      <button type="button" disabled={disabled} aria-pressed={plain} onClick={() => { selection.current = null; lastEmitted.current = null; setPlain(value => !value); }}>Plain text</button>
      {!plain && <>
        <select aria-label="Font" disabled={disabled} defaultValue="Arial" onChange={event => command('fontName', event.target.value)}><option>Arial</option><option>Georgia</option><option>Verdana</option><option>Courier New</option></select>
        <select aria-label="Text size" disabled={disabled} defaultValue="3" onChange={event => command('fontSize', event.target.value)}><option value="2">Small</option><option value="3">Normal</option><option value="5">Large</option><option value="6">Huge</option></select>
        {actions.map(([label, action, text]) => <button key={action} type="button" aria-label={label} title={label} disabled={disabled} onMouseDown={event => event.preventDefault()} onClick={() => command(action, action === 'formatBlock' ? 'blockquote' : undefined)}>{text}</button>)}
        <label className="compose-color">Color<input aria-label="Text color" type="color" disabled={disabled} defaultValue="#222222" onChange={event => command('foreColor', event.target.value)} /></label>
        <button type="button" disabled={disabled} onMouseDown={event => event.preventDefault()} onClick={() => {
          const url = window.prompt('Link URL (https:// or mailto:)');
          if (!url) return;
          if (!/^(https?:\/\/|mailto:)/i.test(url)) { onError('Use an http, https, or mailto link.'); return; }
          const hasSelection = selection.current && !selection.current.collapsed;
          if (hasSelection) command('createLink', url);
          else command('insertHTML', `<a href="${textToHtml(url)}">${textToHtml(url)}</a>`);
        }}>Insert link</button>
        <button type="button" disabled={disabled} onMouseDown={event => event.preventDefault()} onClick={() => imageInput.current?.click()}>Insert image</button>
      </>}
      {signature && <button type="button" disabled={disabled} onMouseDown={event => event.preventDefault()} onClick={() => plain ? onChange(`${body}\n\n${signature}`, null) : command('insertHTML', `<br><br>${textToHtml(signature)}`)}>Insert signature</button>}
      <button type="button" disabled={disabled} onMouseDown={event => event.preventDefault()} onClick={() => {
        const emoji = window.prompt('Insert emoji', '\u{1F60A}');
        if (emoji) { if (plain) onChange(body + emoji, null); else command('insertText', emoji); }
      }}>Emoji</button>
    </div>
    <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/gif,image/webp" hidden aria-label="Inline image file" onChange={event => { void insertImage(event.target.files?.[0]); }} />
    {plain ? <textarea id="email-body" aria-label="Message" value={body} disabled={disabled} spellCheck onChange={event => onChange(event.target.value, null)} placeholder="Write your message..." />
      : <div ref={editor} id="email-body" role="textbox" aria-label="Message" aria-multiline="true" aria-disabled={disabled} contentEditable={!disabled} suppressContentEditableWarning spellCheck data-placeholder="Write your message..." onInput={emit} onKeyUp={rememberSelection} onMouseUp={rememberSelection} onBlur={rememberSelection}
        onPaste={event => {
          event.preventDefault();
          const markup = event.clipboardData.getData('text/html');
          if (markup) command('insertHTML', sanitizeComposeHtml(markup));
          else command('insertText', event.clipboardData.getData('text/plain'));
        }} onDrop={event => {
          event.preventDefault();
          onError('Use Insert image for inline pictures or Attach files for documents.');
        }} />}
  </div>;
}
