/** Logical-asset creation and lifecycle actions of Studio. */
import type { AssetItem } from "./protocol";
import { insertAssetReference, nextAssetId } from "./markdown";
import { fileBase64 } from "./ui-utils";
import type { StudioApp } from "./studio-app";

export class AssetActions {
  constructor(private readonly app: StudioApp) {}

  async createAsset(file: File): Promise<void> {
    if (!(await this.app.resolveDirtyState("创建图形资产"))) return;
    const current = this.app.state.current;
    if (current === null) return;
    const snapshot = this.app.buffer.snapshot();
    const ids = this.app.state.assets.map((item) => item.assetId);
    const assetId = nextAssetId(ids);
    const source = insertAssetReference(snapshot.source, assetId);
    const dataBase64 = await fileBase64(file);
    try {
      const result = await this.app.bridge.request<{ ok: boolean; revision: string }>("asset.create", {
        questionId: current.question.id as string,
        assetId,
        source,
        mediaType: file.type || "image/png",
        dataBase64,
        expectedRevision: current.revision,
      });
      if (!result.ok) throw new Error("资产创建未通过校验");
      await this.app.reloadCurrentQuestion(current.question.id as string, true);
      this.app.toast(`已创建图形资产 ${assetId}`, "success");
    } catch (error) {
      this.app.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  async assetAction(asset: AssetItem, action: string): Promise<void> {
    if (!(await this.app.resolveDirtyState("执行资源操作"))) return;
    const current = this.app.state.current;
    const questionId = current?.question.id;
    if (current === null || typeof questionId !== "string") return;
    const expectedRevision = current.revision;
    const assetId = asset.assetId;
    try {
      if (action === "replace") {
        const input = document.createElement("input");
        input.type = "file";
        input.accept = "image/*,.ipe,.pdf";
        input.addEventListener("change", () => {
          const file = input.files?.[0];
          if (file !== undefined) void this.replaceAsset(questionId, assetId, file);
        });
        input.click();
        return;
      }
      if (action === "replace_clipboard") {
        await this.replaceAssetFromClipboard(questionId, assetId);
        return;
      }
      if (action === "render") {
        await this.app.bridge.request("asset.render", {
          questionId,
          assetId,
          formats: ["svg", "png", "pdf"],
          expectedRevision,
        });
      } else if (action === "reconcile") {
        await this.app.bridge.request("asset.reconcile", {
          questionId,
          assetId,
          expectedRevision,
        });
      } else {
        await this.app.bridge.request("asset.open", {
          questionId,
          assetId,
          action,
          reference: asset.kind === "logical" ? "" : asset.reference,
          expectedRevision,
        });
      }
      if (action === "render" || action === "reconcile") {
        await this.app.reloadCurrentQuestion(questionId, true);
      }
      this.app.toast("资产操作已完成", "success");
    } catch (error) {
      this.app.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  async replaceAsset(questionId: string, assetId: string, file: File): Promise<void> {
    const current = this.app.state.current;
    if (current === null || current.question.id !== questionId) return;
    try {
      await this.app.bridge.request("asset.replace", {
        questionId,
        assetId,
        mediaType: file.type || "image/png",
        dataBase64: await fileBase64(file),
        expectedRevision: current.revision,
      });
      await this.app.reloadCurrentQuestion(questionId, true);
      this.app.toast("已添加新的资源版本", "success");
    } catch (error) {
      this.app.toast(error instanceof Error ? error.message : String(error), "error");
    }
  }

  async replaceAssetFromClipboard(questionId: string, assetId: string): Promise<void> {
    if (navigator.clipboard?.read === undefined) {
      throw new Error("当前 WebView 不支持读取剪贴板图片");
    }
    const items = await navigator.clipboard.read();
    for (const item of items) {
      const mediaType = item.types.find((type) => type.startsWith("image/"));
      if (mediaType === undefined) continue;
      const blob = await item.getType(mediaType);
      const extension = mediaType.split("/")[1]?.replace("jpeg", "jpg") ?? "png";
      await this.replaceAsset(
        questionId,
        assetId,
        new File([blob], `clipboard.${extension}`, { type: mediaType }),
      );
      return;
    }
    throw new Error("剪贴板中没有可用图片");
  }
}
