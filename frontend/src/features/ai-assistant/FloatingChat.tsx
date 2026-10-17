import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { MessageCircle, Minimize2, Maximize2, X } from 'lucide-react';

export function FloatingChat({ title, children }: { title: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const id = useId();
  const launcher = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (open) panel.current?.focus();
  }, [open]);
  useEffect(() => {
    if (!open) return;
    function minimizeOutside(event: PointerEvent) {
      const target = event.target;
      if (!(target instanceof Node) || panel.current?.contains(target) || launcher.current?.contains(target)) return;
      setOpen(false);
      setExpanded(false);
    }
    document.addEventListener('pointerdown', minimizeOutside, true);
    return () => document.removeEventListener('pointerdown', minimizeOutside, true);
  }, [open]);
  function close() { setOpen(false); launcher.current?.focus(); }
  return <>
    <section ref={panel} id={id} hidden={!open} tabIndex={-1} role="dialog" aria-modal="false" aria-label={title}
      className={`floating-chat${expanded ? ' expanded' : ''}`}
      onKeyDown={event => { if (event.key === 'Escape') { event.stopPropagation(); close(); } }}>
      <header className="floating-chat-heading"><strong>{title}</strong><div>
        <button type="button" aria-label={expanded ? 'Collapse chat' : 'Expand chat'} onClick={() => setExpanded(value => !value)}>{expanded ? <Minimize2 size={17} /> : <Maximize2 size={17} />}</button>
        <button type="button" aria-label="Close chat" onClick={close}><X size={19} /></button>
      </div></header>
      <div className="floating-chat-body">{children}</div>
    </section>
    <button ref={launcher} type="button" className="chat-launcher" aria-label={open ? 'Minimize AI chat' : 'Open AI chat'} aria-expanded={open} aria-controls={id}
      onClick={() => open ? close() : setOpen(true)}><MessageCircle size={23} aria-hidden="true" /></button>
  </>;
}
