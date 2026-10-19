import { Plus, X } from 'lucide-react';
import { PRODUCT_AREAS } from './generated/schema';
import type { Environment, Ticket } from './generated/schema';
import { Field } from './components';

function ListField({ label, values, limit, onChange, disabled }: { label: string; values: string[]; limit: number; onChange: (values: string[]) => void; disabled: boolean }) {
  return <fieldset className="list-field" disabled={disabled}><legend>{label}<span className="count">{values.length} / {limit}</span></legend>
    {values.map((value, i) => <div className="list-item" key={i}><input aria-label={`${label} ${i + 1}`} value={value} maxLength={240} onChange={e => onChange(values.map((v, index) => index === i ? e.target.value : v))} /><button className="icon-button" aria-label={`Remove ${label.toLowerCase()} ${i + 1}`} onClick={() => onChange(values.filter((_, index) => index !== i))}><X size={16} /></button></div>)}
    {!disabled && values.length < limit && <button className="text-button" onClick={() => onChange([...values, ''])}><Plus size={14} /> Add {label === 'Follow-up questions' ? 'question' : 'item'}</button>}
    {values.length === 0 && <p className="hint">None listed.</p>}
  </fieldset>;
}

export function TicketEditor({ ticket, onChange, readOnly, source }: { ticket: Ticket; onChange: (ticket: Ticket) => void; readOnly: boolean; source: string | null }) {
  const set = <K extends keyof Ticket>(key: K, value: Ticket[K]) => onChange({ ...ticket, [key]: value });
  const env = ticket.reported_environment;
  const setEnv = (key: keyof Environment, value: string | null) => onChange({ ...ticket, reported_environment: { ...env, [key]: value } });
  return <div className="ticket-fields">
    <Field label="Title"><input value={ticket.title} maxLength={120} readOnly={readOnly} onChange={e => set('title', e.target.value)} /></Field>
    <div className="area-row"><Field label="Suggested product area"><select value={ticket.product_area} disabled={readOnly} onChange={e => { const value = e.target.value as Ticket['product_area']; onChange({ ...ticket, product_area: value, product_area_evidence: value === 'Unknown' ? null : ticket.product_area_evidence }); }}>{PRODUCT_AREAS.map(area => <option key={area}>{area}</option>)}</select></Field><span className="basis-tag reported">Suggested</span></div>
    <Field label="Supporting excerpt" hint={source ? 'Use the exact wording from the customer report.' : 'The original report was not saved; source comparison is unavailable.'}><input value={ticket.product_area_evidence || ''} placeholder="Not established" readOnly={readOnly} maxLength={240} onChange={e => set('product_area_evidence', e.target.value || null)} /></Field>
    <section className="field-section"><div className="section-label"><h3>Actual behavior</h3><span className="basis-tag reported">Reported</span></div><textarea aria-label="Actual behavior" value={ticket.actual_behavior || ''} placeholder="Not reported" rows={3} readOnly={readOnly} maxLength={1000} onChange={e => set('actual_behavior', e.target.value || null)} /></section>
    <section className="field-section"><div className="section-label"><h3>Expected behavior</h3><span className={`basis-tag ${ticket.expected_behavior_basis.toLowerCase()}`}>{ticket.expected_behavior_basis}</span></div><textarea aria-label="Expected behavior" value={ticket.expected_behavior || ''} placeholder="Not reported" rows={3} readOnly={readOnly} maxLength={1000} onChange={e => { const value = e.target.value || null; onChange({ ...ticket, expected_behavior: value, expected_behavior_basis: value ? ticket.expected_behavior_basis === 'Unknown' ? 'Inferred' : ticket.expected_behavior_basis : 'Unknown' }); }} /><Field label="Expectation basis"><select value={ticket.expected_behavior_basis} disabled={readOnly || !ticket.expected_behavior} onChange={e => set('expected_behavior_basis', e.target.value as Ticket['expected_behavior_basis'])}><option>Reported</option><option>Inferred</option>{!ticket.expected_behavior && <option>Unknown</option>}</select></Field></section>
    <section className="field-section"><h3>Reported environment</h3><div className="environment-grid">{(['browser', 'browser_version', 'operating_system', 'app_version'] as const).map(key => <Field key={key} label={{ browser: 'Browser', browser_version: 'Browser version', operating_system: 'Operating system', app_version: 'App version' }[key]}><input value={env[key] || ''} placeholder="Not reported" maxLength={240} readOnly={readOnly} onChange={e => setEnv(key, e.target.value || null)} /></Field>)}</div><ListField label="Other environment details" values={env.other_details} limit={10} disabled={readOnly} onChange={values => onChange({ ...ticket, reported_environment: { ...env, other_details: values } })} /></section>
    <section className="field-section"><ListField label="Reported steps" values={ticket.reported_steps || []} limit={10} disabled={readOnly} onChange={values => set('reported_steps', values.length ? values : null)} /><p className="hint">Include only steps supplied by the customer.</p></section>
    <section className="field-section"><ListField label="Missing information" values={ticket.missing_information} limit={10} disabled={readOnly} onChange={values => set('missing_information', values)} /></section>
    <section className="field-section"><ListField label="Follow-up questions" values={ticket.follow_up_questions} limit={3} disabled={readOnly} onChange={values => set('follow_up_questions', values)} /></section>
  </div>;
}
