<script setup lang="ts">
import { useFrozenPdfPool } from "./frozenPdf";
// Keyed by submission identity in the page: comparison and full-content
// disclosures share documents, then release every worker when that view ends.
useFrozenPdfPool();
</script>
<template><slot /></template>
