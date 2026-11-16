package ru.bstu.equipmentdiag.ui.diagnostics

import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.launch
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import ru.bstu.equipmentdiag.data.DiagApiService
import ru.bstu.equipmentdiag.databinding.ActivityDiagnosticDetailBinding
import ru.bstu.equipmentdiag.model.BarcodeScanRequest

class DiagnosticDetailActivity : AppCompatActivity() {

    private lateinit var binding: ActivityDiagnosticDetailBinding
    private lateinit var apiService: DiagApiService

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityDiagnosticDetailBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val barcode = intent.getStringExtra("EXTRA_BARCODE") ?: "4601234567890"
        binding.tvBarcode.text = "Штрихкод: $barcode"

        initNetwork()
        performDiagnostic(barcode)
    }

    private fun initNetwork() {
        val logging = HttpLoggingInterceptor().apply { level = HttpLoggingInterceptor.Level.BODY }
        val client = OkHttpClient.Builder().addInterceptor(logging).build()

        val retrofit = Retrofit.Builder()
            // 10.0.2.2 - стандартный IP хоста из эмулятора Android Studio, для реального устройства - локальный IP сервера
            .baseUrl("http://10.0.2.2:8000")
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()

        apiService = retrofit.create(DiagApiService::class.java)
    }

    private fun performDiagnostic(barcode: String) {
        binding.progressBar.visibility = View.VISIBLE

        lifecycleScope.launch {
            try {
                // Токен сервисного инженера (демо-авторизация)
                val token = "Bearer dummy_tech_token"
                val req = BarcodeScanRequest(
                    barcode = barcode,
                    departmentId = 1,
                    observedSymptoms = "Сканирование с мобильного терминала Android",
                    externalUrl = null
                )

                val response = apiService.scanBarcode(token, req)
                binding.progressBar.visibility = View.GONE

                if (response.isSuccessful && response.body() != null) {
                    val result = response.body()!!
                    binding.tvModelName.text = "${result.manufacturer} ${result.modelName}"
                    binding.tvCategory.text = "Категория: ${result.category}"
                    binding.tvAction.text = "Действие: ${result.recommendedAction}"
                    binding.tvConclusion.text = result.diagnosticConclusion

                    val defectsBuilder = StringBuilder()
                    for (df in result.matchedMalfunctions) {
                        defectsBuilder.append("• [${df.criticalityLevel}] ${df.title}\n")
                        defectsBuilder.append("  Причина: ${df.possibleRootCause}\n")
                        defectsBuilder.append("  Устранение: ${df.recommendedRemedy}\n\n")
                    }
                    binding.tvDefectsList.text = defectsBuilder.toString()

                    if (result.autoCreatedOrderNumber != null) {
                        binding.tvOrderNotice.visibility = View.VISIBLE
                        binding.tvOrderNotice.text = "Сформирован заказ на ремонт: ${result.autoCreatedOrderNumber}"
                    }
                } else {
                    Toast.makeText(this@DiagnosticDetailActivity, "Ошибка сервера: ${response.code()}", Toast.LENGTH_LONG).show()
                }
            } catch (e: Exception) {
                binding.progressBar.visibility = View.GONE
                Toast.makeText(this@DiagnosticDetailActivity, "Сетевая ошибка: ${e.message}", Toast.LENGTH_LONG).show()
            }
        }
    }
}

