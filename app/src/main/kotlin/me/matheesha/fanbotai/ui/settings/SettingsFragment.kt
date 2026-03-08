package me.matheesha.fanbotai.ui.settings

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import androidx.navigation.fragment.findNavController
import com.google.android.material.snackbar.Snackbar
import me.matheesha.fanbotai.R
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.network.ApiClient
import me.matheesha.fanbotai.data.repository.AuthRepository
import me.matheesha.fanbotai.databinding.FragmentSettingsBinding
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch

class SettingsFragment : Fragment() {

    private var _binding: FragmentSettingsBinding? = null
    private val binding get() = _binding!!

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentSettingsBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        val settings = SettingsRepository.getInstance(requireContext())

        binding.etServerUrl.setText(settings.getServerUrl())
        binding.etApiKey.setText(settings.getApiKey())
        binding.tvCurrentUser.text = settings.getSavedUsername().ifEmpty { "—" }
        binding.tvRole.text        = settings.getSavedRole()

        binding.btnSaveSettings.setOnClickListener {
            val url = binding.etServerUrl.text.toString().trim()
            val key = binding.etApiKey.text.toString().trim()
            if (url.isEmpty()) {
                Snackbar.make(view, "Server URL cannot be empty", Snackbar.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            settings.setServerUrl(url)
            settings.setApiKey(key)
            ApiClient.invalidate()
            Snackbar.make(view, "Settings saved", Snackbar.LENGTH_SHORT).show()
        }

        binding.btnLogout.setOnClickListener {
            val repo = AuthRepository(settings)
            CoroutineScope(Dispatchers.IO).launch {
                repo.logout()
            }
            settings.clearSession()
            ApiClient.invalidate()
            requireActivity().runOnUiThread {
                findNavController().navigate(R.id.action_settingsFragment_to_loginFragment)
            }
        }

        binding.toolbar.setNavigationOnClickListener {
            findNavController().navigateUp()
        }
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

