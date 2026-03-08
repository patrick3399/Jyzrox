"use client";
import { useState, useCallback } from "react";
import useSWR from "swr";
import { api } from "@/lib/api";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { t } from "@/lib/i18n";

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
    <div className="p-8 text-vault-text min-h-screen bg-vault-bg">
      <h1 className="text-3xl font-bold mb-2">{t('export.title')}</h1>
      <p className="text-vault-text-secondary mb-6">
        {t('export.subtitle')}
      </p>

      {/* Search */}
      <div className="mb-6">
        <input
          type="text"
          placeholder={t('export.searchPlaceholder')}
          className="p-3 w-full max-w-md bg-vault-card rounded-lg outline-none focus:ring-2 focus:ring-vault-accent"
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(0); }}
        />
      </div>

      {/* Gallery list */}
      <div className="bg-vault-card rounded-xl overflow-hidden max-w-4xl">
        <table className="w-full text-left">
          <thead className="bg-vault-card-hover">
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
              <tr key={g.id} className="border-t border-vault-border hover:bg-vault-card-hover">
                <td className="p-3 text-vault-text-muted text-sm">{g.id}</td>
                <td className="p-3">
                  <div className="max-w-xs truncate" title={g.title}>
                    {g.title || g.title_jpn || "(untitled)"}
                  </div>
                </td>
                <td className="p-3 text-sm text-vault-text-secondary">{g.source}</td>
                <td className="p-3 text-sm">{g.pages ?? "?"}</td>
                <td className="p-3 text-sm text-vault-text-secondary">{g.tags_array?.length ?? 0}</td>
                <td className="p-3">
                  <button
                    onClick={() => handleExport(g.id)}
                    disabled={exporting === g.id}
                    className={`px-4 py-1.5 rounded text-sm font-medium transition-colors ${
                      exporting === g.id
                        ? "bg-green-700 text-green-200"
                        : g.download_status === "complete"
                          ? "bg-blue-600 hover:bg-blue-500 text-white"
                          : "bg-vault-border hover:bg-vault-card-hover text-vault-text"
                    }`}
                  >
                    {exporting === g.id ? t('export.downloading') : t('export.kohyaZip')}
                  </button>
                </td>
              </tr>
            ))}
            {data?.galleries.length === 0 && (
              <tr><td className="p-4 text-vault-text-muted" colSpan={6}>{t('common.noResults')}</td></tr>
            )}
            {!data && (
              <tr><td className="p-4" colSpan={6}><div className="flex justify-center"><LoadingSpinner /></div></td></tr>
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
            className="px-3 py-1 rounded bg-vault-card-hover hover:bg-vault-card-hover disabled:opacity-30"
          >
            {t('common.prev')}
          </button>
          <span className="text-sm text-vault-text-secondary">
            {page + 1} / {totalPages} ({data?.total} {t('common.galleries')})
          </span>
          <button
            onClick={() => setPage(Math.min(totalPages - 1, page + 1))}
            disabled={page >= totalPages - 1}
            className="px-3 py-1 rounded bg-vault-card-hover hover:bg-vault-card-hover disabled:opacity-30"
          >
            {t('common.next')}
          </button>
        </div>
      )}

      {/* Info box */}
      <div className="mt-8 max-w-4xl bg-vault-card/50 rounded-lg p-4 text-sm text-vault-text-secondary">
        <h3 className="font-semibold text-vault-text mb-2">{t('export.kohyaFormat')}</h3>
        <ul className="list-disc list-inside space-y-1">
          <li>{t('export.kohyaDesc1')}</li>
          <li>{t('export.kohyaDesc2')}</li>
          <li>{t('export.kohyaDesc3')}</li>
          <li>{t('export.kohyaDesc4')}</li>
        </ul>
      </div>
    </div>
  );
}
