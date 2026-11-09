package ru.bstu.equipmentdiag.data

import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST
import ru.bstu.equipmentdiag.model.BarcodeScanRequest
import ru.bstu.equipmentdiag.model.DiagnosticResult

interface DiagApiService {

    @POST("/api/diagnostics/scan")
    suspend fun scanBarcode(
        @Header("Authorization") authHeader: String,
        @Body request: BarcodeScanRequest
    ): Response<DiagnosticResult>
}

