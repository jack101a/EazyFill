import {
  AlertTriangle,
  BrainCircuit,
  Bug,
  CreditCard,
  LayoutDashboard,
  Tag,
  Users,
} from "lucide-react";

export const NAV_SECTIONS = [
  {
    label: "Product",
    items: [
      { path: "/dashboard", label: "Overview", icon: LayoutDashboard },
      { path: "/users", label: "Users", icon: Users },
      { path: "/plans", label: "Plans", icon: Tag },
      { path: "/payments", label: "Payments", icon: CreditCard },
    ],
  },
  {
    label: "Extension",
    items: [
      { path: "/extension-health", label: "Client Health", icon: Bug },
      { path: "/captcha-models", label: "CAPTCHA Models", icon: BrainCircuit },
    ],
  },
  {
    label: "Operations",
    items: [
      { path: "/operations", label: "Risk & Abuse", icon: AlertTriangle },
    ],
  },
];

export const ALL_NAV_ITEMS = NAV_SECTIONS.flatMap((section) => section.items);

export function getNavigationItem(pathname) {
  return ALL_NAV_ITEMS.find((item) => item.path === pathname) || ALL_NAV_ITEMS[0];
}

export const COMPATIBILITY_REDIRECTS = [
  { from: "/subscriptions", to: "/users" },
  { from: "/autofill", to: "/dashboard" },
  { from: "/captcha", to: "/captcha-models" },
  { from: "/userscripts", to: "/dashboard" },
  { from: "/automation", to: "/dashboard" },
  { from: "/settings", to: "/dashboard" },
  { from: "/models", to: "/captcha-models" },
  { from: "/exam", to: "/dashboard" },
  { from: "/legacy/models", to: "/dashboard" },
  { from: "/legacy/exam", to: "/dashboard" },
];
