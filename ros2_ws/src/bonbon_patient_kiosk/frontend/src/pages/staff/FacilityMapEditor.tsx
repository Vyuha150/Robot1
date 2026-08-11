import { useEffect, useState } from "react";
import { ApiClient, NamedLocationLabel } from "../../services/api";

const CATEGORIES = ["room", "doctor", "department", "amenity", "restricted"];

type Draft = {
  name: string; display_label: string; category: string; map_x: number; map_y: number; map_yaw: number; notes: string;
};

const emptyDraft = (): Draft => ({ name: "", display_label: "", category: "room", map_x: 0, map_y: 0, map_yaw: 0, notes: "" });

/** Staff-only, export-only for this pass — see package README. Staff place
 * pins (by typing map coordinates read off bonbon_navigation's map viewer /
 * RViz for now) and export a named_locations YAML block to paste into
 * nav_params.yaml. A future pass can replace the coordinate inputs with a
 * click-to-place map canvas once a map image endpoint exists. */
export function FacilityMapEditor({ api }: { api: ApiClient }) {
  const [labels, setLabels] = useState<NamedLocationLabel[]>([]);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [editingId, setEditingId] = useState<string | null>(null);
  const [yamlText, setYamlText] = useState("");
  const [error, setError] = useState("");

  const refresh = () => api.listFacilityLabels().then(setLabels).catch((e) => setError(String(e)));
  useEffect(() => { refresh(); }, [api]);

  const save = async () => {
    try {
      if (editingId) await api.updateFacilityLabel(editingId, draft);
      else await api.createFacilityLabel(draft);
      setDraft(emptyDraft());
      setEditingId(null);
      setError("");
      refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const edit = (label: NamedLocationLabel) => {
    setEditingId(label.label_id);
    setDraft({
      name: label.name, display_label: label.display_label, category: label.category,
      map_x: label.map_x, map_y: label.map_y, map_yaw: label.map_yaw, notes: label.notes,
    });
  };

  const remove = async (labelId: string) => {
    try { await api.deleteFacilityLabel(labelId); refresh(); } catch (e) { setError(String(e)); }
  };

  const exportYaml = async () => {
    try { const result = await api.exportFacilityMap(); setYamlText(result.yaml_text); }
    catch (e) { setError(String(e)); }
  };

  return (
    <div className="screen staff-screen facility-map-screen">
      <h2>Facility Map Editor</h2>
      <p className="hint-text">
        Export-only for now: labels here generate a named_locations YAML block —
        paste it into bonbon_navigation's nav_params.yaml and relaunch.
      </p>
      {error && <p className="error-text">{error}</p>}

      <div className="facility-form">
        <label>Location key (e.g. room_204)<input className="kiosk-input" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></label>
        <label>Display label<input className="kiosk-input" value={draft.display_label} onChange={(e) => setDraft({ ...draft, display_label: e.target.value })} /></label>
        <label>Category
          <select className="kiosk-input" value={draft.category} onChange={(e) => setDraft({ ...draft, category: e.target.value })}>
            {CATEGORIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </label>
        <label>Map X<input className="kiosk-input" type="number" value={draft.map_x} onChange={(e) => setDraft({ ...draft, map_x: Number(e.target.value) })} /></label>
        <label>Map Y<input className="kiosk-input" type="number" value={draft.map_y} onChange={(e) => setDraft({ ...draft, map_y: Number(e.target.value) })} /></label>
        <label>Yaw<input className="kiosk-input" type="number" value={draft.map_yaw} onChange={(e) => setDraft({ ...draft, map_yaw: Number(e.target.value) })} /></label>
        <div className="btn-row-large">
          <button className="primary" onClick={save} disabled={!draft.name || !draft.display_label}>
            {editingId ? "Update label" : "Add label"}
          </button>
          {editingId && <button className="ghost" onClick={() => { setEditingId(null); setDraft(emptyDraft()); }}>Cancel</button>}
        </div>
      </div>

      <table className="label-table">
        <thead><tr><th>Key</th><th>Label</th><th>Category</th><th>X, Y, Yaw</th><th></th></tr></thead>
        <tbody>
          {labels.map((l) => (
            <tr key={l.label_id}>
              <td>{l.name}</td><td>{l.display_label}</td><td>{l.category}</td>
              <td>{l.map_x}, {l.map_y}, {l.map_yaw}</td>
              <td>
                <button className="ghost small" onClick={() => edit(l)}>Edit</button>
                <button className="ghost small" onClick={() => remove(l.label_id)}>Delete</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <button className="primary" onClick={exportYaml}>Export named_locations YAML</button>
      {yamlText && <pre className="yaml-output">{yamlText}</pre>}
    </div>
  );
}
