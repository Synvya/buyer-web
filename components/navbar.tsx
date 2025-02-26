"use client";

import { Button } from "./ui/button";
import { GitIcon, VercelIcon } from "./icons";
import Link from "next/link";

export const Navbar = () => {
  return (
    <div className="p-2 flex flex-row gap-2 justify-between">
      {/* <Link href="https://github.com/vercel-labs/ai-sdk-preview-python-streaming">
        <Button variant="outline">
          <GitIcon /> View Source Code
        </Button>
      </Link> */}

      <Link href="https://www.downtownsnoqualmie.com">
        <Button>
          <VercelIcon />
          Historic Downtown Snoqualmie Website
        </Button>
      </Link>
    </div>
  );
};
