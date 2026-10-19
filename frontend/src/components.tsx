import { useEffect, useRef } from 'react';
import type { ReactNode } from 'react';
import { AlertCircle, X } from 'lucide-react';

export function Alert({ children }: { children: ReactNode }) {
  return <div className="alert" role="alert"><AlertCircle size={18} /><div>{children}</div></div>;
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return <label className="field"><span className="field-label">{label}</span>{children}{hint && <span className="hint">{hint}</span>}</label>;
}

export function Dialog({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const node = ref.current;
    const previous = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node?.showModal();
    return () => { node?.close(); previous?.focus(); };
  }, []);
  return <dialog ref={ref} onCancel={event => { event.preventDefault(); onClose(); }} aria-labelledby="dialog-title" className="dialog">
    <div className="dialog-header"><h2 id="dialog-title">{title}</h2><button className="icon-button" aria-label="Close dialog" onClick={onClose}><X size={20} /></button></div>
    {children}
  </dialog>;
}
