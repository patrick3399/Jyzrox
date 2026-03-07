"use client";
import { useState } from "react";
import useSWR from "swr";
import Link from "next/link";

const fetcher = (url: string) => fetch(url).then(res => res.json());

export default function Dashboard() {
  const [query, setQuery] = useState("");
  const { data, error } = useSWR(`/api/search?q=${encodeURIComponent(query)}`, fetcher);

  return (
    <div className="p-8 text-white min-h-screen bg-black">
      <header className="flex justify-between items-center mb-10">
        <h1 className="text-4xl font-extrabold tracking-tight text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-600">
          Jyzrox
        </h1>
        <nav className="flex gap-4">
          <Link href="/tags" className="text-neutral-400 hover:text-white transition">Tags</Link>
          <Link href="/queue" className="text-neutral-400 hover:text-white transition">Queue</Link>
        </nav>
      </header>
      
      <div className="mb-10 max-w-2xl">
        <input 
          type="text" 
          placeholder='Try "character:rem title:rezero"' 
          className="p-4 w-full bg-neutral-900 border border-neutral-800 rounded-xl outline-none text-lg focus:ring-2 focus:ring-purple-500 transition-shadow"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-6">
        {!data && !error && <div className="col-span-full">Loading galleries...</div>}
        {data?.items?.map((g: any) => (
          <Link href={`/reader/${g.id}`} key={g.id} className="group cursor-pointer">
            <div className="aspect-[2/3] bg-neutral-800 rounded-lg overflow-hidden mb-3 relative group-hover:ring-2 ring-purple-500 transition-all">
               {/* Thumbnail placeholder */}
               <div className="absolute inset-0 bg-neutral-700 flex items-center justify-center text-neutral-500 text-sm">
                 {g.source}
               </div>
            </div>
            <h3 className="font-semibold text-sm line-clamp-2 leading-tight group-hover:text-purple-400 transition-colors">
              {g.title || "Untitled Gallery"}
            </h3>
            <p className="text-xs text-neutral-500 mt-1">
              {g.tags?.slice(0, 3).join(", ")}
            </p>
          </Link>
        ))}
        {data?.items?.length === 0 && <div className="col-span-full text-neutral-500">No results found.</div>}
      </div>
    </div>
  );
}
