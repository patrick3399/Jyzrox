"use client";
import { useState, useCallback } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";

export default function ExportPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const limit = 20;

  const { data } = useSWR(
    ["export-galleries", search, page],
    () => api.library.getGalleries({ q: search || undefined, page, limit, sort: "added_at" })
  );

  const [exporting, setExporting] = useState<number | null>(null);

  const handleExport = useCallback((galleryId: number) => {
    setExporting(galleryId);
    // Trigger download via hidden link
    const url = api.export.kohyaUrl(galleryId);
    const a = document.createElement("a");
    a.href = url;
    a.download = `gallery_${galleryId}_kohya.zip`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    setTimeout(() => setExporting(null), 2000);
  }, []);

  const totalPages = data ? Math.ceil(data.total / limit) : 0;

  return (
    <div className="p-8 text-white min-h-screen bg-neutral-900">
      <h1 className="text-3xl font-bold mb-2">Training Data Export</h1>
      <p className="text-neutral-400 mb-6">
        Export gallery images + tags in Kohya format (ZIP with images and .txt caption files).
      </p>

      {/* Search */}
      <div className="mb-6">
        <input
          type="text"
          placeholder="Search galleries by title..."
          className="p-3 w-full max-w-md bg-neutral-800 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0); }}
        />
      </div>

      {/* Gallery list */}
      <div className="bg-neutral-800 rounded-xl overflow-hidden max-w-4xl">
        <table className="w-full text-left">
          <thead className="bg-neutral-700">
            <tr>
              <th className="p-3 text-sm">ID</th>
              <th className="p-3 text-sm">Title</th>
              <th className="p-3 text-sm">Source</th>
              <th className="p-3 text-sm">Pages</th>
              <th className="p-3 text-sm">Tags</th>
              <th className="p-3 text-sm">Export</th>
            </tr>
          </thead>
          <tbody>
            {data?.galleries.map((g) => (
              <tr key={g.id} className="border-t border-neutral-700/50 hover:bg-neutral-700/30">
                <td className="p-3 text-neutral-500 text-sm">{g.id}</td>
                <td className="p-3">
                  <div className="max-w-xs truncate" title={g.title}>
                    {g.title || g.title_jpn || "(untitled)"}
                  </div>
                </td>
                <td className="p-3 text-sm text-neutral-400">{g.source}</td>
                <td className="p-3 text-sm">{g.pages ?? "?"}</td>
                <td className="p-3 text-sm text-neutral-400">{g.tags_array?.length ?? 0}</td>
                <td className="p-3">
                  <button
                    onClick={() => handleExport(g.id)}
                    disabled={exporting === g.id}
                    className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
                      exporting === g.id
                        ? "bg-green-700 text-green-200"
                        : g.download_status === "complete"
                          ? "bg-blue-600 hover:bg-blue-500 text-white"
                          : "bg-neutral-600 hover:bg-neutral-500 text-neutral-300"
                    }`}
                  >
                    {exporting === g.id ? "Downloading..." : "Kohya ZIP"}
                  </button>
                </td>
              </tr>
            ))}
            {data?.galleries.length === 0 && (
              <tr><td className="p-4 text-neutral-500" colSpan={6}>No galleries found</td></tr>
            )}
            {!data && (
              <tr><td className="p-4 text-neutral-500" colSpan={6}>Loading...</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex gap-2 mt-4 items-center max-w-4xl">
          <button
            onClick={() => setPage(Math.max(0, page - 1))}
            disabled={page === 0}
            className="px-3 py-1 rounded bg-neutral-700 hover:bg-neutral-600 disabled:opacity-30"
          >
            Prev
          </button>
          <span className="text-sm text-neutral-400">
            {page + 1} / {totalPages} ({data?.total} galleries)
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

      {/* Info box */}
      <div className="mt-8 max-w-4xl bg-neutral-800/50 rounded-lg p-4 text-sm text-neutral-400">
        <h3 className="font-semibold text-neutral-300 mb-2">Kohya Format</h3>
        <ul className="list-disc list-inside space-y-1">
          <li>Each image is paired with a .txt file containing comma-separated tags</li>
          <li>Tags include both gallery-level and image-level tags</li>
          <li>Only locally downloaded images are included in the export</li>
          <li>Compatible with Kohya_ss, EveryDream2, and other fine-tuning tools</li>
        </ul>
      </div>
    </div>
  );
}
