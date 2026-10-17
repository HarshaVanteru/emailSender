import { useEffect, useRef, useState } from 'react';
import { buildEmailDocument } from './emailDocument';

export function MailBody({ html, text }: { html: string | null; text: string | null }) {
  const frame = useRef<HTMLIFrameElement>(null);
  const cleanup = useRef<(() => void) | undefined>(undefined);
  const [view, setView] = useState({ html, plain: false, images: false });
  const plain = view.html === html && view.plain;
  const images = view.html === html && view.images;
  const [rendered, setRendered] = useState<{
    html: string; images: boolean; document: string; hasRemoteImages: boolean; failed: boolean;
  } | null>(null);
  const current = rendered?.html === html && rendered.images === images ? rendered : null;

  useEffect(() => {
    let active = true;
    if (!html || plain) return;
    void buildEmailDocument(html, images).then(result => {
      if (active) setRendered({ html, images, ...result, failed: false });
    }).catch(() => {
      if (active) setRendered({ html, images, document: '', hasRemoteImages: false, failed: true });
    });
    return () => { active = false; };
  }, [html, plain, images]);
  useEffect(() => () => cleanup.current?.(), [html, plain, images]);

  function resizeFrame() {
    cleanup.current?.();
    const element = frame.current;
    const body = element?.contentDocument?.body;
    if (!element || !body) return;
    // Measuring the body lets a responsive message shrink as well as grow.
    const resize = () => {
      element.style.height = `${Math.min(12000, Math.max(80, Math.ceil(body.getBoundingClientRect().height)))}px`;
    };
    const observer = new ResizeObserver(resize);
    observer.observe(body);
    resize();
    cleanup.current = () => observer.disconnect();
  }

  const formatted = Boolean(html && !plain && !current?.failed);
  return <div className="message-body">
    {html && <div className="message-view-controls">
      {text && <button type="button" className="mail-text-button" onClick={() => setView({ html, plain: !plain, images })}>{plain ? 'Show formatted message' : 'Show plain text'}</button>}
      {formatted && current?.hasRemoteImages && <button type="button" className="mail-text-button" onClick={() => setView({ html, plain, images: !images })}>{images ? 'Hide images' : 'Show images'}</button>}
      {formatted && current?.hasRemoteImages && !images && <span className="mail-muted">External images are hidden.</span>}
    </div>}
    {current?.failed && <p role="status" className="mail-muted">Formatting could not be displayed. Showing available plain text.</p>}
    {formatted ? current?.document ? <iframe
      ref={frame}
      title="Formatted email"
      className="mail-html-frame"
      sandbox="allow-same-origin allow-popups allow-popups-to-escape-sandbox"
      referrerPolicy="no-referrer"
      srcDoc={current.document}
      onLoad={resizeFrame}
    /> : <p role="status" className="mail-muted">Loading formatted message...</p>
      : <div className="mail-body mail-plain">{text || 'No plain-text content is available.'}</div>}
  </div>;
}
