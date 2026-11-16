package ru.bstu.equipmentdiag.model

import com.google.gson.annotations.SerializedName

data class BarcodeScanRequest(
    @SerializedName("barcode") val barcode: String,
    @SerializedName("department_id") val departmentId: Int,
    @SerializedName("observed_symptoms") val observedSymptoms: String?,
    @SerializedName("external_marketplace_url") val externalUrl: String?
)

data class MalfunctionPattern(
    @SerializedName("id") val id: Int,
    @SerializedName("code") val code: String,
    @SerializedName("title") val title: String,
    @SerializedName("symptom_description") val symptomDescription: String,
    @SerializedName("possible_root_cause") val possibleRootCause: String,
    @SerializedName("criticality_level") val criticalityLevel: String,
    @SerializedName("recommended_remedy") val recommendedRemedy: String,
    @SerializedName("occurrence_frequency_pct") val occurrenceFrequencyPct: Float?
)

data class DiagnosticResult(
    @SerializedName("log_id") val logId: Int,
    @SerializedName("equipment_id") val equipmentId: Int,
    @SerializedName("scanned_barcode") val scannedBarcode: String,
    @SerializedName("model_name") val modelName: String,
    @SerializedName("manufacturer") val manufacturer: String,
    @SerializedName("category") val category: String,
    @SerializedName("observed_symptoms") val observedSymptoms: String,
    @SerializedName("matched_malfunctions") val matchedMalfunctions: List<MalfunctionPattern>,
    @SerializedName("diagnostic_conclusion") val diagnosticConclusion: String,
    @SerializedName("recommended_action") val recommendedAction: String,
    @SerializedName("auto_created_order_number") val autoCreatedOrderNumber: String?
)

