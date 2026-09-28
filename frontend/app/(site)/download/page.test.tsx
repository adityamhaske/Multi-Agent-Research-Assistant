import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RELEASES } from "@/lib/releases";

import DownloadPage from "./page";

const LATEST = RELEASES.find((r) => !r.unreleased && r.version !== "v1.0.0")!.version.replace(
  /^v/,
  "",
);

describe("DownloadPage", () => {
  it("renders the version selector defaulting to the latest version", () => {
    render(<DownloadPage />);
    const select = screen.getByLabelText(/version/i) as HTMLSelectElement;
    expect(select).toBeInTheDocument();
    expect(select.value).toBe(LATEST);
  });

  it("renders download buttons at the bottom of all platform boxes with subtle styling", () => {
    render(<DownloadPage />);

    // macOS button
    const macBtn = screen.getByRole("link", {
      name: new RegExp(`download \\.dmg · v${LATEST}`, "i"),
    });
    expect(macBtn).toBeInTheDocument();
    expect(macBtn).toHaveClass("btn-secondary");
    expect(macBtn.getAttribute("href")).toContain(
      `releases/download/v${LATEST}/Research.Assistant_${LATEST}_aarch64.dmg`,
    );

    // Windows button
    const winBtn = screen.getByRole("link", {
      name: new RegExp(`download \\.msi · v${LATEST}`, "i"),
    });
    expect(winBtn).toBeInTheDocument();
    expect(winBtn).toHaveClass("btn-secondary");
    expect(winBtn.getAttribute("href")).toContain(
      `releases/download/v${LATEST}/Research.Assistant_${LATEST}_x64_en-US.msi`,
    );

    // Linux buttons (both AppImage and deb)
    const linuxAppImage = screen.getByRole("link", {
      name: new RegExp(`download \\.appimage · v${LATEST}`, "i"),
    });
    expect(linuxAppImage).toBeInTheDocument();
    expect(linuxAppImage).toHaveClass("btn-secondary");
    expect(linuxAppImage.getAttribute("href")).toContain(
      `releases/download/v${LATEST}/Research.Assistant_${LATEST}_amd64.AppImage`,
    );

    const linuxDeb = screen.getByRole("link", {
      name: new RegExp(`download \\.deb · v${LATEST}`, "i"),
    });
    expect(linuxDeb).toBeInTheDocument();
    expect(linuxDeb).toHaveClass("btn-secondary");
    expect(linuxDeb.getAttribute("href")).toContain(
      `releases/download/v${LATEST}/Research.Assistant_${LATEST}_amd64.deb`,
    );

    // Docker localhost button
    const dockerZip = screen.getByRole("link", { name: /download source \(\.zip\)/i });
    expect(dockerZip).toBeInTheDocument();
    expect(dockerZip).toHaveClass("btn-secondary");
    expect(dockerZip.getAttribute("href")).toContain(`archive/refs/tags/v${LATEST}.zip`);

    const dockerGuide = screen.getByRole("link", { name: /docker deployment guide/i });
    expect(dockerGuide).toBeInTheDocument();
    expect(dockerGuide).toHaveClass("btn-secondary");
  });

  it("says the Mac build is Apple Silicon only, and where an Intel Mac goes instead", () => {
    render(<DownloadPage />);
    expect(
      screen.getByRole("heading", { name: "macOS — Apple Silicon (M1+)" }),
    ).toBeInTheDocument();
    expect(screen.getByText(/There is no Intel build/)).toHaveTextContent(/Docker \/ Localhost/);
  });

  it("claims no compatibility broader than the builds that exist", () => {
    const { container } = render(<DownloadPage />);
    expect(container).not.toHaveTextContent(/last decade/);
    expect(container).not.toHaveTextContent(/any laptop/);
    expect(container).toHaveTextContent(/Apple Silicon\s+Macs and 64-bit \(x86-64\) Windows and Linux/);
  });

  it("updates download links when a different version is selected", () => {
    render(<DownloadPage />);
    const select = screen.getByLabelText(/version/i) as HTMLSelectElement;

    fireEvent.change(select, { target: { value: "2.0.1" } });

    const macBtn = screen.getByRole("link", { name: /download \.dmg · v2\.0\.1/i });
    expect(macBtn.getAttribute("href")).toContain(
      "releases/download/v2.0.1/Research.Assistant_2.0.1_aarch64.dmg",
    );

    const winBtn = screen.getByRole("link", { name: /download \.msi · v2\.0\.1/i });
    expect(winBtn.getAttribute("href")).toContain(
      "releases/download/v2.0.1/Research.Assistant_2.0.1_x64_en-US.msi",
    );

    const dockerZip = screen.getByRole("link", { name: /download source \(\.zip\)/i });
    expect(dockerZip.getAttribute("href")).toContain("archive/refs/tags/v2.0.1.zip");
  });

  // Every macOS build up to 3.0.0 is reported as "damaged" once downloaded — its signature
  // was incomplete — and System Settings offers no way past that state. The one step that
  // opens every version this page offers is clearing the quarantine flag, recursively, on
  // the installed app; a card that led with "Open Anyway" sent people to a button that
  // never appears for those builds.
  it("gives macOS the command that opens every offered version, copyable and exact", () => {
    render(<DownloadPage />);
    const card = screen.getByRole("region", { name: /macos/i });
    const command = 'xattr -dr com.apple.quarantine "/Applications/Research Assistant.app"';
    expect(within(card).getByText(command)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: /copy the command/i })).toBeInTheDocument();
    expect(within(card).getByText(/damaged and can.t be opened/i)).toBeInTheDocument();
  });
});
