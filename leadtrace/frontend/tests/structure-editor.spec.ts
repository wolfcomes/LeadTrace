import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import StructureComparison from "../src/structures/StructureComparison.vue";
import StructureEditor from "../src/structures/StructureEditor.vue";
import MoleculeProposalInspector from "../src/review/workspace/MoleculeProposalInspector.vue";
import StructureInspector from "../src/review/workspace/StructureInspector.vue";
import { useAuthStore } from "../src/auth/store";
import {
  createStructure,
  drawStructure,
  updateStructure,
  validateStructure,
} from "../src/review/api";

function jsonResponse(body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}

describe("source-aware structure review", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    useAuthStore().acceptSession({
      user: { username: "reviewer.one", display_name: "Reviewer", role: "reviewer", must_change_password: false },
      csrf_token: "csrf-token",
    });
  });
  it("labels RDKit success as parseable and requires source plus reason", async () => {
    const wrapper = mount(StructureEditor, {
      props: {
        modelValue: {
          smiles: "CCO",
          source: "",
          reason: "",
          structureState: "parseable_candidate",
        },
        validation: { parseable: true, messages: [], componentCount: 1 },
        editable: true,
      },
    });

    expect(wrapper.get("form").classes()).toEqual(expect.arrayContaining(["editor-form", "panel"]));
    expect(wrapper.get("[data-parse-status]").classes()).toContain("status-chip");
    expect(wrapper.findAll("label.form-field").length).toBeGreaterThanOrEqual(3);
    expect(wrapper.get("button[type='submit']").classes()).toContain("button-primary");
    expect(wrapper.get("[data-parse-status]").text()).toBe("RDKit 可解析");
    expect(wrapper.get("button[type='submit']").attributes("disabled")).toBeDefined();

    await wrapper.get("[name='source']").setValue("SI, Table S2");
    await wrapper.get("[name='reason']").setValue("人工核对来源结构");
    expect(wrapper.get("button[type='submit']").attributes("disabled")).toBeUndefined();
  });

  it("compares published and draft drawings without requiring smiles for non-unique material", () => {
    const wrapper = mount(StructureComparison, {
      props: {
        published: { label: "已发布", imageUrl: "/published.png", smiles: "CCO" },
        draft: {
          label: "草稿",
          imageUrl: null,
          smiles: null,
          structureState: "non_unique_stereochemistry",
        },
      },
    });

    expect(wrapper.findAll("[data-structure-side]")).toHaveLength(2);
    expect(wrapper.findAll("[data-structure-side].panel")).toHaveLength(2);
    expect(wrapper.get("[data-structure-side] .status-chip").text()).toContain("非唯一立体化学");
    expect(wrapper.text()).toContain("非唯一立体化学");
  });

  it("keeps source comparison and multicomponent selection explicit", async () => {
    const wrapper = mount(StructureEditor, {
      props: {
        modelValue: {
          smiles: "CCO.Cl",
          selectedComponentSmiles: null,
          source: "Figure 1",
          reason: "Review salt form",
          structureState: "multicomponent_unresolved",
          experimentalMaterial: "multicomponent",
          sourceComparison: "not_compared",
          sourceVerified: false,
          humanConfirmed: false,
        },
        validation: {
          parseable: true,
          messages: ["EXACT_COMPONENT_SELECTION_REQUIRED"],
          componentCount: 2,
          eligibleStates: ["proposal", "multicomponent_unresolved"],
        },
        editable: true,
      },
    });

    expect(wrapper.get("select[name='experimental-material']").element).toHaveProperty("value", "multicomponent");
    expect(wrapper.get("select[name='source-comparison']").element).toHaveProperty("value", "not_compared");
    expect(wrapper.find("input[name='selected-component']").exists()).toBe(true);
    expect(wrapper.get("[data-validation-messages]").text()).toContain("EXACT_COMPONENT_SELECTION_REQUIRED");
    await wrapper.get("input[name='source-verified']").setValue(true);
    expect(wrapper.emitted("update:modelValue")?.at(-1)?.[0]).toMatchObject({ sourceVerified: true });
  });

  it("shows all OCSR machine evidence and emits only typed Reviewer decisions", async () => {
    const proposal = {
      id: "10000000-0000-4000-8000-000000000001",
      paper_id: "10000000-0000-4000-8000-000000000002",
      visual_object_id: "10000000-0000-4000-8000-000000000003",
      proposal_key: "ocsr-1",
      model_run_key: "run-1",
      revision_id: "10000000-0000-4000-8000-000000000004",
      disposition: "pending" as const,
      machine: {
        raw_values: {
          raw_smiles: "CCO.Cl",
          token_confidences: [{ token: "Cl", confidence: 0.31 }],
          inference_error: "low contrast",
          model_version: "ocsr-v2",
        },
        normalized_values: {
          canonical_smiles: "CCO.Cl",
          mean_token_confidence: 0.81,
          min_token_confidence: 0.31,
          rdkit_status: "parseable",
          proposal_quality: "low",
        },
      },
      review: {},
      crop_asset: null,
      source_region_id: null,
    };
    const wrapper = mount(MoleculeProposalInspector, {
      props: {
        proposal,
        structures: [],
        editable: true,
        validation: {
          inputSmiles: "CCO.Cl",
          parseable: true,
          canonicalSmiles: "CCO.Cl",
          canonicalIsomericSmiles: "CCO.Cl",
          formula: null,
          molecularWeight: null,
          componentCount: 2,
          selectedComponentSmiles: null,
          messages: ["EXACT_COMPONENT_SELECTION_REQUIRED"],
          eligibleStates: ["proposal", "multicomponent_unresolved"],
        },
      },
    });

    const machine = wrapper.get("[data-machine-evidence]");
    expect(machine.text()).toContain("CCO.Cl");
    expect(machine.text()).toContain("ocsr-v2");
    expect(machine.text()).toContain("31%");
    expect(machine.text()).toContain("low contrast");
    expect(wrapper.get("[data-low-confidence-token]").text()).toContain("Cl");
    expect(wrapper.find("[name='machine-smiles']").exists()).toBe(false);
    expect(wrapper.find("input[name='selected-component-smiles']").exists()).toBe(true);

    await wrapper.get("input[name='compound-id']").setValue("10000000-0000-4000-8000-000000000005");
    await wrapper.get("input[name='selected-component-smiles']").setValue("CCO");
    await wrapper.get("[data-accept-proposal]").trigger("click");
    expect(wrapper.emitted("decision")?.[0]?.[0]).toMatchObject({
      disposition: "accepted",
      reviewed_smiles: "CCO.Cl",
      selected_component_smiles: "CCO",
      compound_id: "10000000-0000-4000-8000-000000000005",
    });
  });

  it("requires rationale for rejection and a valid structure for acceptance", async () => {
    const proposal = {
      id: "10000000-0000-4000-8000-000000000001",
      paper_id: "10000000-0000-4000-8000-000000000002",
      visual_object_id: "10000000-0000-4000-8000-000000000003",
      proposal_key: "ocsr-1",
      model_run_key: "run-1",
      revision_id: "10000000-0000-4000-8000-000000000004",
      disposition: "pending" as const,
      machine: { raw_values: { raw_smiles: "invalid" }, normalized_values: {} },
      review: {},
      crop_asset: null,
      source_region_id: null,
    };
    const wrapper = mount(MoleculeProposalInspector, {
      props: { proposal, structures: [], editable: true, validation: null },
    });

    expect(wrapper.get("[data-accept-proposal]").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-correct-proposal]").attributes("disabled")).toBeDefined();
    expect(wrapper.get("[data-reject-proposal]").attributes("disabled")).toBeDefined();
    await wrapper.get("textarea[name='rationale']").setValue("Not a chemical structure");
    expect(wrapper.get("[data-reject-proposal]").attributes("disabled")).toBeUndefined();
    await wrapper.get("[data-reject-proposal]").trigger("click");
    expect(wrapper.emitted("decision")?.[0]?.[0]).toMatchObject({
      disposition: "rejected",
      rationale: "Not a chemical structure",
    });
  });

  it("wraps Structure editing with a stable RDKit drawing fallback", async () => {
    const structure = {
      id: "10000000-0000-4000-8000-000000000001",
      compound_id: "10000000-0000-4000-8000-000000000002",
      structure_key: "structure-1",
      revision_id: "10000000-0000-4000-8000-000000000003",
      state: "source_bound_candidate" as const,
      canonical_smiles: "CCO",
      snapshot: {
        input_smiles: "CCO",
        source: "Figure 1",
        source_comparison: "match",
        source_verified: true,
        human_confirmed: false,
        experimental_material: "unique",
      },
    };
    const wrapper = mount(StructureInspector, {
      props: { structure, editable: true, validation: null, drawingUrl: null },
    });

    expect(wrapper.get("[data-structure-inspector]").text()).toContain("structure-1");
    expect(wrapper.get("[data-structure-drawing]").classes()).toContain("evidence-preview-frame");
    expect(wrapper.get("[data-drawing-fallback]").text()).toContain("尚未生成 RDKit 图");
    await wrapper.get("button[data-draw-structure]").trigger("click");
    expect(wrapper.emitted("draw")?.[0]).toEqual(["CCO"]);
  });

  it("uses typed Structure validate, drawing, create, and update APIs", async () => {
    const calls: Array<[string | undefined, string]> = [];
    vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const path = new URL(String(input), "http://leadtrace.test").pathname;
      calls.push([init?.method, path]);
      if (path.endsWith("/validate")) return jsonResponse({
        input_smiles: "CCO", parseable: true, canonical_smiles: "CCO", canonical_isomeric_smiles: "CCO",
        formula: "C2H6O", molecular_weight: 46.07, component_count: 1, selected_component_smiles: null,
        has_dummy_atoms: false, has_radicals: false, has_stereochemistry: false, is_salt: false,
        experimental_material: "unique", source_comparison: "match", messages: [],
        eligible_states: ["proposal", "parseable_candidate", "source_bound_candidate"],
      });
      if (path.endsWith("/drawings")) return jsonResponse({
        asset_id: "10000000-0000-4000-8000-000000000010", drawing_key: "draw-1", sha256: "a".repeat(64), width: 600, height: 420, reused: false,
      });
      return jsonResponse({
        id: "10000000-0000-4000-8000-000000000001", paper_id: "10000000-0000-4000-8000-000000000002",
        compound_id: "10000000-0000-4000-8000-000000000003", structure_key: "structure-1",
        revision_id: "10000000-0000-4000-8000-000000000004", revision_number: 2,
        changeset_version: 4, snapshot: {}, structure_state: "parseable_candidate", workflow_state: "draft",
      });
    }));
    const review = {
      changeset_id: "10000000-0000-4000-8000-000000000005", expected_version: 3,
      smiles: "CCO", selected_component_smiles: null, experimental_material: "unique" as const,
      source_comparison: "match" as const, source_verified: true, human_confirmed: false,
      structure_state: "parseable_candidate" as const, source: "Figure 1", reason: "Checked source",
      compound_id: "10000000-0000-4000-8000-000000000003", structure_key: "structure-1",
    };

    await validateStructure("paper-1", review);
    await drawStructure("paper-1", { smiles: "CCO" });
    await createStructure("paper-1", review);
    await updateStructure("paper-1", "structure-1", review);
    expect(calls).toEqual([
      ["POST", "/api/v1/papers/paper-1/structures/validate"],
      ["POST", "/api/v1/papers/paper-1/structures/drawings"],
      ["POST", "/api/v1/papers/paper-1/structures"],
      ["PATCH", "/api/v1/papers/paper-1/structures/structure-1"],
    ]);
  });
});
