# Execução local e rotina diária

## Comandos
| Ação | Comando (dentro da pasta, com o `.venv` ativo) |
|---|---|
| Abrir o painel | `streamlit run app.py` ou `iniciar_windows.bat` |
| Pesquisa completa agora | `python run_pipeline.py` |
| Monitor de urgentes | `python run_pipeline.py --mode urgente` |
| Exportar Excel | `python run_pipeline.py --excel leads.xlsx` |
| Só o relatório do dia | `python run_pipeline.py --report` |
| Agendador local | `python scheduler_service.py` ou `agendador_windows.bat` |
| Testes | `python -m pytest -q tests` |

Para ativar o `.venv` manualmente no Windows: `.venv\Scripts\activate`.

## Rotina sugerida (20 a 40 minutos por dia)
1. **08:00 · Oportunidades urgentes:** responda primeiro às demandas explícitas e licitações com prazo curto.
2. **Central de abordagem > "Ainda sem abordagem" + "Com e-mail disponível":** abra cada lead com score ≥ 60,
   revise o texto, marque a aprovação, clique em **Abrir no Outlook**, envie e clique em **Registrar e-mail enviado**.
   Os follow-ups de 3, 5 e 7 dias são agendados automaticamente.
3. **"Follow-up para hoje/vencido":** as mensagens de follow-up já estão prontas na etapa correspondente.
4. **Leads sem contato com score alto:** procure o responsável (site oficial, página da empresa no LinkedIn,
   recepção) e cadastre em **Contatos** informando a fonte. A abordagem é refeita com o nome.
5. **Quando a empresa responder:** registre em **CRM > Empresa respondeu**. Os follow-ups param.
6. **Sexta-feira:** exporte o Excel em **Relatórios** e revise o pipeline.

## Onde ficam os arquivos
| Pasta | Conteúdo |
|---|---|
| `data/logistics.db` | banco SQLite (faça backup copiando este arquivo) |
| `data/relatorios/` | relatórios diários em texto |
| `logs/` | logs técnicos (credenciais são ocultadas automaticamente) |
| `.env` | suas credenciais (não compartilhe) |
