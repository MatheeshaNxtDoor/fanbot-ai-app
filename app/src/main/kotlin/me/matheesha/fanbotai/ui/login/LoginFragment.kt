package me.matheesha.fanbotai.ui.login

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.core.view.isVisible
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.navigation.fragment.findNavController
import com.google.android.material.snackbar.Snackbar
import me.matheesha.fanbotai.R
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.network.ApiClient
import me.matheesha.fanbotai.databinding.FragmentLoginBinding
import me.matheesha.fanbotai.ui.UiState

class LoginFragment : Fragment() {
    private var _binding: FragmentLoginBinding? = null
    private val binding get() = _binding!!

    private val viewModel: LoginViewModel by viewModels {
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return LoginViewModel(SettingsRepository.getInstance(requireContext())) as T
            }
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentLoginBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        val settings = SettingsRepository.getInstance(requireContext())
        binding.etServerUrl.setText(settings.getServerUrl())
        binding.etApiKey.setText(settings.getApiKey())

        if (settings.isLoggedIn() && settings.getServerUrl().isNotEmpty()) {
            findNavController().navigate(R.id.action_loginFragment_to_dashboardFragment)
            return
        }

        binding.btnLogin.setOnClickListener {
            val serverUrl = binding.etServerUrl.text.toString().trim()
            val apiKey    = binding.etApiKey.text.toString().trim()
            val username  = binding.etUsername.text.toString().trim()
            val password  = binding.etPassword.text.toString().trim()
            val totp      = binding.etTotp.text.toString().trim().ifEmpty { null }

            if (serverUrl.isEmpty()) { Snackbar.make(view, "Server URL is required", Snackbar.LENGTH_SHORT).show(); return@setOnClickListener }
            if (username.isEmpty() || password.isEmpty()) { Snackbar.make(view, "Username and password are required", Snackbar.LENGTH_SHORT).show(); return@setOnClickListener }

            settings.setServerUrl(serverUrl)
            settings.setApiKey(apiKey)
            ApiClient.invalidate()
            viewModel.login(username, password, totp)
        }

        viewModel.needsTotp.observe(viewLifecycleOwner) { needs ->
            binding.tilTotp.isVisible = needs
            if (needs) Snackbar.make(view, "Enter your 2FA code", Snackbar.LENGTH_SHORT).show()
        }

        viewModel.loginState.observe(viewLifecycleOwner) { state ->
            when (state) {
                is UiState.Loading -> { binding.btnLogin.isEnabled = false; binding.progressBar.isVisible = true }
                is UiState.Success -> { binding.btnLogin.isEnabled = true; binding.progressBar.isVisible = false; findNavController().navigate(R.id.action_loginFragment_to_dashboardFragment) }
                is UiState.Error   -> { binding.btnLogin.isEnabled = true; binding.progressBar.isVisible = false; Snackbar.make(view, state.message, Snackbar.LENGTH_LONG).show() }
                else               -> { binding.btnLogin.isEnabled = true; binding.progressBar.isVisible = false }
            }
        }
    }

    override fun onDestroyView() { super.onDestroyView(); _binding = null }
}

