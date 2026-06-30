import type { ElementView, SectionView, UnitView } from "../types";

// Pick the most "telemetry-interesting" element of a unit to headline.
function headline(u: UnitView): ElementView | undefined {
  return (
    u.elements.find((e) => ["temp", "pressure", "level", "flow"].includes(e.signal)) ??
    u.elements[0]
  );
}

function Dot({ status }: { status: string }) {
  return <span className={`dot s-${status}`} title={status} />;
}

function Unit({ u }: { u: UnitView }) {
  const h = headline(u);
  return (
    <div className={`unit s-${u.status}`} data-testid={`unit-${u.id}`} data-status={u.status}>
      <Dot status={u.status} />
      <span className="unit-name" title={u.name}>
        {u.name}
      </span>
      {h && (
        <span className="unit-tele">
          {h.value}
          <span className="unit-tele-u">{h.unit}</span>
        </span>
      )}
      <span className="unit-elcount">
        {u.elements.filter((e) => e.in_alarm || e.in_trip).length > 0 && (
          <span className="el-alarm">!{u.elements.filter((e) => e.in_alarm || e.in_trip).length}</span>
        )}
      </span>
    </div>
  );
}

export function SectionCard({ section, status }: { section: SectionView; status: string }) {
  return (
    <section className={`section-card s-${status}`} data-testid={`section-${section.id}`} data-status={status}>
      <header className="section-head">
        <Dot status={status} />
        <span className="section-id">{section.id}</span>
        <span className="section-name">{section.name}</span>
        <span className="section-net">
          {section.network.map((n) => (
            <Dot key={n.tag} status={n.state} />
          ))}
        </span>
      </header>
      <div className="section-units">
        {section.units.map((u) => (
          <Unit key={u.id} u={u} />
        ))}
      </div>
    </section>
  );
}
