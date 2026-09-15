import type { Metadata } from "next";
import fs from "node:fs";
import path from "node:path";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";

export const metadata: Metadata = {
  title: "Methodology",
  description: "How PriceIntegrity separates lawful dynamic pricing from personalized pricing: randomized factorial probing, robust regression on log price, Benjamini-Hochberg correction, and how each claim is tested.",
};

export default function MethodologyPage() {
  const md = fs.readFileSync(path.join(process.cwd(), "src/data/methodology.md"), "utf8");
  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-10 sm:py-14 prose-pi">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          table: ({ children }) => <div className="table-wrap"><table>{children}</table></div>,
        }}
      >
        {md}
      </ReactMarkdown>
    </div>
  );
}
