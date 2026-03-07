"use client";
import { useState } from "react";
import useSWR from "swr";

const fetcher = (url: string) => fetch(url).then(res => res.json());

export default function TagsPage() {
  const [search, setSearch] = useState("");
  const { data: tags, error } = useSWR(`/api/tags?prefix=${search}&limit=50`, fetcher);

  return (
    <div className="p-8 text-white min-h-screen bg-neutral-900">
      <h1 className="text-3xl font-bold mb-6">Tag Management</h1>
      
      <div className="mb-6">
        <input 
          type="text" 
          placeholder="Search tags..." 
          className="p-3 w-full max-w-md bg-neutral-800 rounded-lg outline-none focus:ring-2 focus:ring-blue-500"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="bg-neutral-800 rounded-xl overflow-hidden max-w-3xl">
        <table className="w-full text-left">
          <thead className="bg-neutral-700">
            <tr>
              <th className="p-4">Namespace</th>
              <th className="p-4">Name</th>
              <th className="p-4">Count</th>
              <th className="p-4">Actions</th>
            </tr>
          </thead>
          <tbody>
            {!tags && !error && <tr><td className="p-4" colSpan={4}>Loading...</td></tr>}
            {tags?.map((t: any) => (
              <tr key={t.id} className="border-t border-neutral-700/50 hover:bg-neutral-700/30">
                <td className="p-4 text-neutral-400">{t.namespace}</td>
                <td className="p-4 font-mono text-blue-400">{t.name}</td>
                <td className="p-4">{t.count}</td>
                <td className="p-4">
                  <button className="text-sm bg-neutral-700 hover:bg-neutral-600 px-3 py-1 rounded mr-2">Alias</button>
                  <button className="text-sm bg-neutral-700 hover:bg-neutral-600 px-3 py-1 rounded">Imply</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
