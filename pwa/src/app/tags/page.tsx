"use client";
import { useState, useCallback } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import type { TagItem, TagAlias, TagImplication } from "@/lib/types";

export default function TagsPage() {
  const [search, setSearch] = useState("");
  const [nsFilter, setNsFilter] = useState("");
  const [page, setPage] = useState(0);
  const limit = 50;

  // Selected tag for alias/implication panel
  const [selectedTag, setSelectedTag] = useState<TagItem | null>(null);

  // Tags list
  const { data: tagData, mutate: mutateTags } = useSWR(
    ["tags", search, nsFilter, page],
    () => api.tags.list({ prefix: search || undefined, namespace: nsFilter || undefined, limit, offset: page * limit })
  );

  // Aliases for selected tag
  const { data: aliases, mutate: mutateAliases } = useSWR(
    selectedTag ? ["aliases", selectedTag.id] : null,
    () => api.tags.listAliases({ tag_id: selectedTag!.id })
  );

  // Implications for selected tag
  const { data: implications, mutate: mutateImplications } = useSWR(
    selectedTag ? ["implications", selectedTag.id] : null,
    () => api.tags.listImplications({ tag_id: selectedTag!.id })
  );

  // ── Alias form state ──
  const [aliasNs, setAliasNs] = useState("");
  const [aliasName, setAliasName] = useState("");

  const handleAddAlias = useCallback(async () => {
    if (!selectedTag || !aliasName.trim()) return;
    try {
      await api.tags.createAlias(aliasNs || selectedTag.namespace, aliasName.trim(), selectedTag.id);
      setAliasNs("");
      setAliasName("");
      mutateAliases();
    } catch (e: any) {
      alert(e.message);
    }
  }, [selectedTag, aliasNs, aliasName, mutateAliases]);

  const handleDeleteAlias = useCallback(async (ns: string, name: string) => {
    try {
      await api.tags.deleteAlias(ns, name);
      mutateAliases();
    } catch (e: any) {
      alert(e.message);
    }
  }, [mutateAliases]);

  // ── Implication form state ──
  const [implTargetId, setImplTargetId] = useState("");
  const [implDirection, setImplDirection] = useState<"implies" | "implied_by">("implies");

  const handleAddImplication = useCallback(async () => {
    if (!selectedTag || !implTargetId) return;
    const targetId = parseInt(implTargetId);
    if (isNaN(targetId)) return;
    try {
      if (implDirection === "implies") {
        await api.tags.createImplication(selectedTag.id, targetId);
      } else {
        await api.tags.createImplication(targetId, selectedTag.id);
      }
      setImplTargetId("");
      mutateImplications();
    } catch (e: any) {
      alert(e.message);
    }
  }, [selectedTag, implTargetId, implDirection, mutateImplications]);

  const handleDeleteImplication = useCallback(async (antId: number, conId: number) => {
    try {
      await api.tags.deleteImplication(antId, conId);
      mutateImplications();
    } catch (e: any) {
      alert(e.message);
    }
  }, [mutateImplications]);

  const totalPages = tagData ? Math.ceil(tagData.total / limit) : 0;

  return (
    <div className="p-8 text-white min-h-screen bg-neutral-900">
      <h1 className="text-3xl font-bold mb-6">Tag Management</h1>

      {/* Filters */}
      <div className="mb-6 flex gap-3 flex-wrap">
        <input
          type="text"
          placeholder="Search by name..."
          className="p-3 w-64 bg-neutral-800 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0); }}
        />
        <input
          type="text"
          placeholder="Namespace filter..."
          className="p-3 w-48 bg-neutral-800 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
          value={nsFilter}
          onChange={(e) => { setNsFilter(e.target.value); setPage(0); }}
        />
      </div>

      <div className="flex gap-6 flex-col lg:flex-row">
        {/* Tag table */}
        <div className="flex-1">
          <div className="bg-neutral-800 rounded-xl overflow-hidden">
            <table className="w-full text-left">
              <thead className="bg-neutral-700">
                <tr>
                  <th className="p-3 text-sm">ID</th>
                  <th className="p-3 text-sm">Namespace</th>
                  <th className="p-3 text-sm">Name</th>
                  <th className="p-3 text-sm">Count</th>
                </tr>
              </thead>
              <tbody>
                {tagData?.tags.map((t) => (
                  <tr
                    key={t.id}
                    className={`border-t border-neutral-700/50 cursor-pointer transition-colors ${
                      selectedTag?.id === t.id ? "bg-blue-900/30" : "hover:bg-neutral-700/30"
                    }`}
                    onClick={() => setSelectedTag(t)}
                  >
                    <td className="p-3 text-neutral-500 text-sm">{t.id}</td>
                    <td className="p-3 text-neutral-400 text-sm">{t.namespace}</td>
                    <td className="p-3 font-mono text-blue-400">{t.name}</td>
                    <td className="p-3">{t.count}</td>
                  </tr>
                ))}
                {tagData?.tags.length === 0 && (
                  <tr><td className="p-4 text-neutral-500" colSpan={4}>No tags found</td></tr>
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex gap-2 mt-4 items-center">
              <button
                onClick={() => setPage(Math.max(0, page - 1))}
                disabled={page === 0}
                className="px-3 py-1 rounded bg-neutral-700 hover:bg-neutral-600 disabled:opacity-30"
              >
                Prev
              </button>
              <span className="text-sm text-neutral-400">
                {page + 1} / {totalPages} ({tagData?.total} tags)
              </span>
              <button
                onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
                disabled={page >= totalPages - 1}
                className="px-3 py-1 rounded bg-neutral-700 hover:bg-neutral-600 disabled:opacity-30"
              >
                Next
              </button>
            </div>
          )}
        </div>

        {/* Detail panel */}
        {selectedTag && (
          <div className="w-full lg:w-96 space-y-6">
            {/* Selected tag info */}
            <div className="bg-neutral-800 rounded-xl p-4">
              <h2 className="text-lg font-semibold mb-2">
                <span className="text-neutral-400">{selectedTag.namespace}:</span>{selectedTag.name}
              </h2>
              <p className="text-sm text-neutral-400">ID: {selectedTag.id} | Count: {selectedTag.count}</p>
            </div>

            {/* Aliases */}
            <div className="bg-neutral-800 rounded-xl p-4">
              <h3 className="text-md font-semibold mb-3">Aliases</h3>
              {aliases && aliases.length > 0 ? (
                <ul className="space-y-1 mb-3">
                  {aliases.map((a) => (
                    <li key={`${a.alias_namespace}:${a.alias_name}`} className="flex items-center justify-between text-sm">
                      <span className="font-mono">
                        <span className="text-neutral-400">{a.alias_namespace}:</span>{a.alias_name}
                      </span>
                      <button
                        onClick={() => handleDeleteAlias(a.alias_namespace, a.alias_name)}
                        className="text-red-400 hover:text-red-300 text-xs px-2 py-0.5 rounded bg-red-900/20"
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-neutral-500 mb-3">No aliases</p>
              )}

              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="ns"
                  className="p-2 w-16 bg-neutral-700 rounded text-sm outline-none"
                  value={aliasNs}
                  onChange={(e) => setAliasNs(e.target.value)}
                />
                <input
                  type="text"
                  placeholder="alias name"
                  className="p-2 flex-1 bg-neutral-700 rounded text-sm outline-none"
                  value={aliasName}
                  onChange={(e) => setAliasName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddAlias()}
                />
                <button
                  onClick={handleAddAlias}
                  className="px-3 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium"
                >
                  Add
                </button>
              </div>
            </div>

            {/* Implications */}
            <div className="bg-neutral-800 rounded-xl p-4">
              <h3 className="text-md font-semibold mb-3">Implications</h3>
              {implications && implications.length > 0 ? (
                <ul className="space-y-1 mb-3">
                  {implications.map((imp) => (
                    <li key={`${imp.antecedent_id}-${imp.consequent_id}`} className="flex items-center justify-between text-sm">
                      <span className="font-mono">
                        <span className="text-orange-400">{imp.antecedent}</span>
                        <span className="text-neutral-500 mx-1">&rarr;</span>
                        <span className="text-green-400">{imp.consequent}</span>
                      </span>
                      <button
                        onClick={() => handleDeleteImplication(imp.antecedent_id, imp.consequent_id)}
                        className="text-red-400 hover:text-red-300 text-xs px-2 py-0.5 rounded bg-red-900/20"
                      >
                        Remove
                      </button>
                    </li>
                  ))}
                </ul>
              ) : (
                <p className="text-sm text-neutral-500 mb-3">No implications</p>
              )}

              <div className="flex gap-2">
                <select
                  className="p-2 bg-neutral-700 rounded text-sm outline-none"
                  value={implDirection}
                  onChange={(e) => setImplDirection(e.target.value as "implies" | "implied_by")}
                >
                  <option value="implies">implies &rarr;</option>
                  <option value="implied_by">&larr; implied by</option>
                </select>
                <input
                  type="number"
                  placeholder="Target tag ID"
                  className="p-2 flex-1 bg-neutral-700 rounded text-sm outline-none"
                  value={implTargetId}
                  onChange={(e) => setImplTargetId(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleAddImplication()}
                />
                <button
                  onClick={handleAddImplication}
                  className="px-3 py-2 bg-blue-600 hover:bg-blue-500 rounded text-sm font-medium"
                >
                  Add
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
