package ru.bstu.equipmentdiag.ui

import android.Manifest
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Bundle
import android.widget.Button
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import ru.bstu.equipmentdiag.R
import ru.bstu.equipmentdiag.ui.scanner.BarcodeScannerActivity

class MainActivity : AppCompatActivity() {

    private val CAMERA_PERMISSION_CODE = 1001

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val btnScan = findViewById<Button>(R.id.btnScanBarcode)
        btnScan.setOnClickListener {
            if (checkCameraPermission()) {
                startScanning()
            } else {
                requestCameraPermission()
            }
        }
    }

    private fun checkCameraPermission(): Boolean {
        return ContextCompat.checkSelfPermission(
            this,
            Manifest.permission.CAMERA
        ) == PackageManager.PERMISSION_GRANTED
    }

    private fun requestCameraPermission() {
        ActivityCompat.requestPermissions(
            this,
            arrayOf(Manifest.permission.CAMERA),
            CAMERA_PERMISSION_CODE
        )
    }

    private fun startScanning() {
        val intent = Intent(this, BarcodeScannerActivity::class.java)
        startActivity(intent)
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == CAMERA_PERMISSION_CODE) {
            if (grantResults.isNotEmpty() && grantResults[0] == PackageManager.PERMISSION_GRANTED) {
                startScanning()
            } else {
                Toast.makeText(this, "Для сканирования требуется разрешение на камеру", Toast.LENGTH_SHORT).show()
            }
        }
    }
}

