"use client";

import Link from "next/link";
import { SubmitForm } from "@/components/SubmitForm";

export default function NewJobPage() {
  return (
    <main className="max-w-2xl mx-auto p-8">
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-semibold">New generation</h1>
        <Link href="/" className="text-sm text-muted hover:text-white">← Library</Link>
      </div>
      <SubmitForm />
    </main>
  );
}
