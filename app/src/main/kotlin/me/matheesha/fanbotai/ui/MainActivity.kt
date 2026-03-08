package me.matheesha.fanbotai.ui

import android.os.Build
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.isVisible
import androidx.navigation.fragment.NavHostFragment
import androidx.navigation.ui.setupWithNavController
import com.google.firebase.messaging.FirebaseMessaging
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import me.matheesha.fanbotai.R
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.repository.DeviceRepository
import me.matheesha.fanbotai.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {

    private lateinit var binding: ActivityMainBinding

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        val navHost = supportFragmentManager.findFragmentById(R.id.nav_host_fragment) as NavHostFragment
        val navController = navHost.navController
        binding.bottomNavigation.setupWithNavController(navController)

        // Hide bottom nav on login screen
        navController.addOnDestinationChangedListener { _, destination, _ ->
            binding.bottomNavigation.isVisible = destination.id != R.id.loginFragment
        }

        refreshFcmToken()
    }

    private fun refreshFcmToken() {
        val settings = SettingsRepository.getInstance(applicationContext)
        FirebaseMessaging.getInstance().token.addOnSuccessListener { token ->
            if (token.isNullOrEmpty()) return@addOnSuccessListener
            val existing = settings.getFcmToken()
            settings.setFcmToken(token)
            if (token != existing && settings.isLoggedIn() && settings.getServerUrl().isNotEmpty()) {
                CoroutineScope(Dispatchers.IO).launch {
                    DeviceRepository(settings).registerDevice(token, Build.MODEL)
                }
            }
        }
    }
}

