"use client";

import NextLink from "next/link";
import type { ComponentProps, ReactNode } from "react";

type Props = ComponentProps<typeof NextLink> & {
  children: ReactNode;
};

/**
 * Thin re-export of Next.js Link that preserves language context automatically.
 * We don't currently mutate the href because we use URL-only routing without a
 * /[lang] prefix. If we switch to prefix routing we wrap here.
 */
export const Link = ({ children, ...rest }: Props) => {
  return <NextLink {...rest}>{children}</NextLink>;
};
