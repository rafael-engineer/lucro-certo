import json
import os
import time
from datetime import datetime

import openai
import pandas as pd
import streamlit as st
from azure.cosmos import CosmosClient
from dotenv import load_dotenv

load_dotenv()

ENDPOINT = os.getenv("COSMOS_ENDPOINT")
KEY = os.getenv("COSMOS_KEY")
DATABASE_NAME = "LucroCertoDB"
CONTAINER_USERS = "Users"
CONTAINER_TRANS = "Transactions"
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ADMIN_KEY_FOR_PROFILE_CREATION = os.getenv("ADMIN_KEY_FOR_PROFILE_CREATION")

st.set_page_config(page_title="Lucro Certo Pro", page_icon="🧑‍🍳", layout="wide")

# --- CSS CUSTOMIZADO ---
st.markdown("""
<style>
    .metric-card {
        background-color: #f0f2f6;
        padding: 15px;
        border-radius: 10px;
        border: 1px solid #e0e0e0;
    }
    .stButton>button {
        width: 100%;
        border-radius: 20px;
    }
    .warning-box {
        background-color: #ffcccc;
        padding: 10px;
        border-radius: 5px;
        border: 1px solid #ff0000;
        color: #990000;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

MOTIVOS_DESPERDICIO = {
    "Estoque / Armazenamento": [
        "Produto vencido", "Produto deteriorado", "Armazenamento inadequado (temp)",
        "Armazenamento inadequado (umidade/luz)", "Embalagem danificada",
        "Produto aberto sem uso", "Excesso de compra", "Praga no estoque",
        "Falha na organização (FIFO)", "Reprovado no recebimento",
        "Extraviado no estoque", "Queda no transporte interno"
    ],
    "Preparo / Cozinha": [
        "Erro de manipulação", "Erro de porcionamento", "Erro de receita",
        "Queima / cozimento excessivo", "Sobra de preparo", "Descarte de aparas úteis",
        "Contaminação cruzada", "Utensílio contaminado", "Textura inadequada",
        "Impróprio após reaquecer"
    ],
    "Serviço / Atendimento": [
        "Sobra de buffet", "Devolvido pelo cliente", "Excesso de reposição",
        "Exposto tempo excessivo", "Erro no pedido", "Apresentação inadequada"
    ],
    "Operacional / Infraestrutura": [
        "Falha de refrigeração", "Falha elétrica", "Avaria no transporte",
        "Quebra de vidro", "Infiltração", "Queda de estantes", "Infestação"
    ],
    "Higiene / Segurança": [
        "Contaminação cruzada", "Sem EPI", "Exposto sem proteção",
        "Falha em boas práticas", "Rejeição visual/olfativa", "Superfície suja",
        "Temperatura insegura"
    ],
    "Gestão / Processos": [
        "Inventário incorreto", "Falha de comunicação", "Compra inadequada",
        "Cardápio mal planejado", "Erro administrativo", "Treinamento insuficiente"
    ]
}

LISTA_MOTIVOS = []
for cat, motivos in MOTIVOS_DESPERDICIO.items():
    for m in motivos:
        LISTA_MOTIVOS.append(f"{cat} - {m}")
LISTA_MOTIVOS.sort()


@st.cache_resource
def get_db_containers():
    """
    Inicializa e retorna os clients/containers do Azure Cosmos DB.

    Retorna:
        tuple: (users_container, trans_container) — ou (None, None) em caso de erro.
    """
    try:
        client = CosmosClient(ENDPOINT, KEY)
        database = client.get_database_client(DATABASE_NAME)
        users_container = database.get_container_client(CONTAINER_USERS)
        trans_container = database.get_container_client(CONTAINER_TRANS)
        return users_container, trans_container
    except Exception as e:
        st.error(f"Erro de Conexão Azure: {e}")
        return None, None


# --- LÓGICA DE NEGÓCIO ---

def authenticate(email, password):
    """
    Autentica um usuário consultando o container de Users.

    Args:
        email (str): email/ID do usuário.
        password (str): senha em texto simples para validação.

    Returns:
        dict|None: objeto do usuário se autenticado; caso contrário None.
    """
    users_container, _ = get_db_containers()
    if not users_container: return None
    try:
        user = users_container.read_item(item=email, partition_key=email)
        if user['password'] == password: return user
    except:
        return None
    return None


def save_transaction(transaction_data, user_id):
    """
    Persiste (insere/atualiza) uma transação no container de Transactions.

    Se 'id' não existir em transaction_data, gera um id baseado em timestamp.
    Normaliza description (strip + upper) quando presente.

    Args:
        transaction_data (dict): dados da transação.
        user_id (str): partition_key / email do usuário.
    """
    _, trans_container = get_db_containers()
    if not trans_container: return
    if 'id' not in transaction_data:
        transaction_data['id'] = str(int(time.time() * 1000000))
        transaction_data['created_at'] = datetime.utcnow().isoformat()

    transaction_data['user_id'] = user_id
    transaction_data['last_updated'] = datetime.utcnow().isoformat()

    if 'description' in transaction_data:
        transaction_data['description'] = transaction_data['description'].strip().upper()

    trans_container.upsert_item(body=transaction_data)


def get_transactions(user_id):
    """
    Recupera todas as transações de um usuário.

    Args:
        user_id (str): partition_key / email do usuário.

    Returns:
        list: lista de dicionários representando transações.
    """
    _, trans_container = get_db_containers()
    query = "SELECT * FROM c WHERE c.user_id = @user_id"
    params = [{"name": "@user_id", "value": user_id}]
    return list(trans_container.query_items(query=query, parameters=params, enable_cross_partition_query=True))


def update_product_name(user_id, old_names, new_name, new_unit):
    """
    Atualiza, em massa, ocorrências antigas de nomes de produtos no histórico.

    Ignora transações do tipo 'receita_produto' e 'venda_produto'.

    Args:
        user_id (str): partition_key / email do usuário.
        old_names (list): lista de nomes que devem ser substituídos.
        new_name (str): novo nome padrão (será upper+strip).
        new_unit (str): unidade padrão para unit_measure.

    Returns:
        int: quantidade de registros atualizados.
    """
    _, trans_container = get_db_containers()
    all_trans = get_transactions(user_id)
    count = 0
    for item in all_trans:
        if item.get('type') in ['receita_produto', 'venda_produto']:
            continue
        if item.get('description') in old_names:
            item['description'] = new_name.strip().upper()
            item['unit_measure'] = new_unit
            trans_container.upsert_item(body=item)
            count += 1
    return count


def delete_stock_items(user_id, item_names=None, delete_all=False):
    """
    Exclui itens do histórico de transações.

    Args:
        user_id (str): partition_key / email do usuário.
        item_names (list|None): nomes específicos a excluir (se delete_all for False).
        delete_all (bool): se True, exclui todas as transações.

    Returns:
        int: número de itens efetivamente excluídos.
    """
    _, trans_container = get_db_containers()
    all_trans = get_transactions(user_id)
    count = 0
    for item in all_trans:
        should_delete = False
        if delete_all:
            should_delete = True
        elif item_names and item.get('description') in item_names:
            should_delete = True

        if should_delete:
            try:
                trans_container.delete_item(item=item['id'], partition_key=user_id)
                count += 1
            except Exception as e:
                print(f"Erro ao deletar {item.get('id', 'unknown')}: {e}")
    return count


def delete_transaction(item_id, user_id):
    """
    Deleta uma transação pelo id.

    Args:
        item_id (str): id da transação.
        user_id (str): partition_key / email do usuário.

    Returns:
        bool: True se deletado com sucesso, False caso contrário.
    """
    _, trans_container = get_db_containers()
    try:
        trans_container.delete_item(item=item_id, partition_key=user_id)
        return True
    except Exception as e:
        st.error(f"Erro ao deletar: {e}")
        return False


def get_inventory_dataframe(transactions, include_zero_stock=False):
    """
    Constrói um DataFrame de inventário a partir de uma lista de transações.

    O DataFrame resultante sempre terá as colunas:
    ["Ingrediente", "Unidade", "Qtd em Estoque", "Preço Médio", "Valor Total"]

    Args:
        transactions (list): lista de transações (dicts).
        include_zero_stock (bool): se True, inclui itens com quantidade zero.

    Returns:
        pandas.DataFrame: DataFrame com o inventário resumido.
    """
    cols = ["Ingrediente", "Unidade", "Qtd em Estoque", "Preço Médio", "Valor Total"]

    # If no transactions, return an empty DataFrame with the right columns
    if not transactions:
        return pd.DataFrame(columns=cols)

    # Create DataFrame and defensive processing
    df = pd.DataFrame(transactions)
    estoque = {}

    # iterate safely (use .iterrows but guard missing keys)
    for _, row in df.iterrows():
        t = row.get('type', None)
        
        item = row.get('description') or row.get('product_name') or 'Unknown'
        
        # FIX: Ignore summary records for sales and waste, as they are not stock items.
        # Their impact on stock is handled by separate ingredient-level transactions.
        if item.startswith('VENDA:') or item.startswith('DESP:'):
            continue

        if t not in ['compra', 'venda', 'desperdicio', 'uso_receita', 'uso_receita_negativo', 'ajuste_manual',
                     'venda_produto', 'receita_produto']:
            continue

        try:
            qtd = float(row.get('qty', 0) or 0)
        except Exception:
            qtd = 0.0
        try:
            total = float(row.get('total', 0) or 0)
        except Exception:
            total = 0.0

        unit_measure = row.get('unit_measure', row.get('unit', 'UN') or 'UN')

        if item not in estoque:
            estoque[item] = {'qtd': 0.0, 'custo_total': 0.0, 'preco_medio': 0.0, 'unidade': unit_measure}

        if t in ['compra', 'ajuste_manual']:
            estoque[item]['qtd'] += qtd
            estoque[item]['custo_total'] += total
        elif t in ['venda', 'venda_produto', 'desperdicio', 'uso_receita', 'uso_receita_negativo']:
            estoque[item]['qtd'] -= qtd
            # if we already have preco_medio, reduce custo_total accordingly
            if estoque[item]['preco_medio'] > 0:
                estoque[item]['custo_total'] -= (qtd * estoque[item]['preco_medio'])

        # Recalculate price average when possible
        if estoque[item]['qtd'] > 0:
            try:
                estoque[item]['preco_medio'] = estoque[item]['custo_total'] / estoque[item]['qtd']
            except Exception:
                estoque[item]['preco_medio'] = 0.0
        else:
            # keep preco_medio at 0 if qtd <= 0 and no historical price
            if estoque[item]['preco_medio'] == 0:
                estoque[item]['preco_medio'] = 0.0

    data = []
    for nome, dados in estoque.items():
        if include_zero_stock or dados['qtd'] != 0:
            data.append({
                "Ingrediente": nome,
                "Unidade": dados.get('unidade', 'UN'),
                "Qtd em Estoque": dados.get('qtd', 0.0),
                "Preço Médio": dados.get('preco_medio', 0.0),
                "Valor Total": dados.get('qtd', 0.0) * dados.get('preco_medio', 0.0)
            })

    # Ensure returned DataFrame always has the expected columns
    if not data:
        return pd.DataFrame(columns=cols)

    return pd.DataFrame(data)[cols]


# --- IA (OPENAI) ---
def process_receipt_image(uploaded_file, existing_items=[]):
    """
    Envia imagem para o serviço OpenAI (via client multimodal) para extrair
    dados estruturados da nota fiscal (loja, data, itens).

    Args:
        uploaded_file (UploadedFile): arquivo enviado via Streamlit file_uploader.
        existing_items (list): lista de itens existentes no estoque para contexto.

    Returns:
        dict|None: JSON parseado retornado pelo modelo, ou None em caso de erro.
    """
    if not OPENAI_API_KEY:
        st.error("Configure a OPENAI_API_KEY no .env")
        return None

    client = openai.OpenAI(api_key=OPENAI_API_KEY)
    import base64
    base64_image = base64.b64encode(uploaded_file.getvalue()).decode('utf-8')

    items_context = ""
    if existing_items:
        items_list_str = ", ".join([f"'{item}'" for item in existing_items])
        items_context = f"""
        CONTEXTO DE ESTOQUE:
        O usuário já possui os seguintes itens no estoque: [{items_list_str}].
        Ao extrair o nome de um item da nota, verifique se ele corresponde a algum item desta lista.
        Se for o mesmo produto (mesmo com pequena variação de nome na nota), USE O NOME DA LISTA DE ESTOQUE.
        """

    prompt = f"""
    Você é um especialista em OCR de notas fiscais de alimentos.
    Analise esta imagem. Extraia:
    1. Nome do Estabelecimento.
    2. Data da emissão (Formato YYYY-MM-DD). Se não achar, use hoje.
    3. Lista de itens. Para cada item:
       {items_context}
       
       - Nome: Se não encontrou no contexto de estoque, REMOVA marca para normalizar, EXCETO se for marca relevante (Doritos, Coca-Cola).
       
       - Unidade e Qtd:
         Extraia: 'count' (qtd itens) e 'unit_size' (tamanho unitário base G/ML).
         Se Unidade for 'UN', unit_size = 1.
         
       - Valor TOTAL pago (líquido).
    
    Retorne APENAS um JSON:
    {{
        "store": "Nome",
        "date": "YYYY-MM-DD",
        "total_receipt": 0.00,
        "items": [
            {{"name": "LEITE INTEGRAL", "count": 7.0, "unit_size": 1000.0, "unit": "ML", "total": 34.93}}
        ]
    }}
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
                ]}
            ],
            max_tokens=1000,
            temperature=0.1
        )
        content = response.choices[0].message.content.replace("```json", "").replace("```", "")
        return json.loads(content)
    except Exception as e:
        st.error(f"Erro na IA: {e}")
        return None


# --- CALLBACKS PARA ESTADO ---
def load_recipe_to_edit(recipe):
    """
    Carrega um objeto 'receita_produto' no session_state para edição no editor.

    Args:
        recipe (dict): dicionário representando a receita a ser editada.
    """
    st.session_state.recipe_items = recipe.get('ingredients', [])
    st.session_state.extra_costs = recipe.get('extras', [])
    st.session_state.target_profit = float(recipe.get('profit_margin', 100.0))
    st.session_state.target_price = float(recipe.get('sale_price', 0.0))
    st.session_state.product_name = recipe.get('description', '')
    st.session_state.editing_recipe_id = recipe.get('id')
    st.session_state.widget_profit = st.session_state.target_profit
    st.session_state.widget_price = st.session_state.target_price


def main():
    """
    Inicializa e renderiza a interface Streamlit da aplicação Lucro Certo.

    Essa função orquestra toda a interação do usuário com a aplicação:
    - controla o fluxo de autenticação (login / criação de perfil admin),
    - carrega transações e inventário do Cosmos DB,
    - exibe o menu lateral com navegação para as áreas principais:
      "Visão Geral", "Estoque & Compras", "Receitas & Produtos", "Vendas" e "Desperdícios",
    - trata ações do usuário (adicionar compras, ler nota via OCR/IA, criar/editar
      receitas, registrar vendas e desperdícios, ajustar/normalizar estoque),
    - persiste alterações chamando funções auxiliares como `save_transaction`,
      `delete_transaction`, `update_product_name`, `get_transactions` e `get_inventory_dataframe`.

    Efeitos colaterais / comportamento importante:
    - Lê e modifica `st.session_state` (chaves usadas/afetadas):
        - 'user' (objeto de usuário autenticado)
        - 'view' (controla a tela de não-logado: 'home' ou 'login')
        - 'recipe_items' (lista de ingredientes no editor)
        - 'extra_costs' (custos extras do produto)
        - 'editing_recipe_id' (id da receita em edição)
        - 'product_name', 'target_profit', 'target_price', 'widget_profit', 'widget_price'
        - 'ocr_data' (resultado do processamento de imagem/receipts)
    - Faz chamadas a Azure Cosmos DB via `get_db_containers()` para ler/gravar transações.
    - Usa `process_receipt_image()` para OCR/extração de notas (depende de OPENAI_API_KEY).
    - Mostra mensagens de erro/aviso diretamente na UI com `st.error`, `st.warning`, `st.success` e `st.info`.
    - Realiza `st.rerun()` em pontos onde é necessário recarregar a interface após alterações persistidas.
    - Não retorna valor — toda interação é realizada via UI e efeitos colaterais.

    Pré-requisitos / variáveis de ambiente:
    - Espera que as variáveis de ambiente (injetadas pelo ambiente/Azure) estejam disponíveis:
        COSMOS_ENDPOINT, COSMOS_KEY, OPENAI_API_KEY, ADMIN_KEY_FOR_PROFILE_CREATION
    - O container/ambiente deve ter rede e permissões para acessar o Cosmos DB e a API OpenAI,
      quando aplicável.

    Observações de implementação:
    - A função foi projetada para ser a camada de apresentação — toda a lógica de persistência e
      processamento está delegada a funções auxiliares. Mantenha essa separação ao ajustar o código.
    - Evite modificar fluxos de `st.session_state` aqui sem refletir as mudanças nas funções auxiliares,
      pois a UI depende fortemente dessas chaves.
    """
    if 'user' not in st.session_state: st.session_state.user = None
    if 'view' not in st.session_state: st.session_state.view = 'home'
    if 'recipe_items' not in st.session_state: st.session_state.recipe_items = []
    if 'extra_costs' not in st.session_state: st.session_state.extra_costs = []
    if 'editing_recipe_id' not in st.session_state: st.session_state.editing_recipe_id = None
    if 'product_name' not in st.session_state: st.session_state.product_name = ""
    if 'target_profit' not in st.session_state: st.session_state.target_profit = 100.0
    if 'target_price' not in st.session_state: st.session_state.target_price = 0.0

    if st.session_state.user is None:
        if st.session_state.view == 'home':
            st.title("🧑‍🍳 Lucro Certo")
            st.header("Gestão Inteligente de Custos para Microempreendedores Alimentícios")

            st.markdown("""
            O **Lucro Certo** é uma aplicação web desenvolvida para transformar a gestão financeira de microempreendedores do setor alimentício.
            A ferramenta simplifica radicalmente o controle de estoque, a precificação e o gerenciamento de desperdícios,
            substituindo planilhas complexas por automação inteligente.
            """)

            # WhatsApp button styling and link
            whatsapp_button_style = """
                <style>
                .whatsapp-button {
                    background-color: #25D366;
                    color: white !important;
                    padding: 10px 24px;
                    text-align: center;
                    text-decoration: none;
                    display: inline-block;
                    font-size: 18px;
                    font-weight: bold;
                    margin: 10px 2px;
                    cursor: pointer;
                    border-radius: 12px;
                    border: none;
                }
                .whatsapp-button:hover {
                    background-color: #128C7E;
                    text-decoration: none;
                    color: white !important;
                }
                </style>
                """
            st.markdown(whatsapp_button_style, unsafe_allow_html=True)
            whatsapp_link = "https://wa.me/5553991615661?text=Ol%C3%A1!%20Vi%20o%20site%20de%20voc%C3%AAs%20e%20gostaria%20de%20solicitar%20acesso%20ao%20Lucro%20Certo!"
            st.markdown(f'<a href="{whatsapp_link}" target="_blank" class="whatsapp-button">Quero usar o Lucro Certo de graça!</a>', unsafe_allow_html=True)

            st.markdown("---")

            if st.button("Fazer Login"):
                st.session_state.view = 'login'
                st.rerun()

            st.divider()

            st.subheader("Contato")
            st.markdown("""
            **Rafael da Silva Santos**
            - **LinkedIn:** [Rafael da Silva Santos](https://www.linkedin.com/in/rafael-engineer/)
            - **Portfólio:** [https://www.rafael.engineer](https://www.rafael.engineer)
            """)

        elif st.session_state.view == 'login':
            st.title("Login - Lucro Certo")
            if st.button("⬅️ Voltar para a página inicial"):
                st.session_state.view = 'home'
                st.rerun()

            with st.form("login"):
                email = st.text_input("Email")
                password = st.text_input("Senha", type="password")
                if st.form_submit_button("Entrar"):
                    user = authenticate(email, password)
                    if user:
                        st.session_state.user = user
                        st.session_state.view = 'home'  # Reset view state on login
                        st.rerun()
                    else:
                        st.error("Email ou senha incorretos.")

            if st.checkbox("Admin: Criar novo usuário"):
                with st.form("create"):
                    new_e = st.text_input("Novo Email")
                    new_n = st.text_input("Nome Completo")
                    new_p = st.text_input("Nova Senha", type="password")
                    key = st.text_input("Chave de Administrador", type="password")
                    if st.form_submit_button("Criar Usuário"):
                        if key == ADMIN_KEY_FOR_PROFILE_CREATION:
                            users_container, _ = get_db_containers()
                            try:
                                users_container.read_item(item=new_e, partition_key=new_e)
                                st.error("Usuário com este email já existe.")
                            except:
                                users_container.create_item({"id": new_e, "email": new_e, "password": new_p, "name": new_n})
                                st.success("Usuário criado com sucesso! Você já pode fazer o login.")
                        else:
                            st.error("Chave de administrador incorreta.")

    else:
        user = st.session_state.user
        transactions = get_transactions(user['email'])
        df_trans = pd.DataFrame(transactions)
        
        if df_trans.empty:
            df_trans = pd.DataFrame(
                columns=['type', 'total', 'qty', 'description', 'product_name', 'waste_item', 'waste_reason', 'id', 'related_sale_id'])
        
        # --- Data Preparation ---
        # 1. Get a clean list of manageable ingredients (items that were bought or manually adjusted)
        ingredient_trans = df_trans[df_trans['type'].isin(['compra', 'ajuste_manual'])]
        valid_ingredients = ingredient_trans['description'].unique().tolist() if not ingredient_trans.empty else []

        # 2. Get the full inventory calculation
        df_estoque_full = get_inventory_dataframe(transactions, include_zero_stock=True)

        # 3. Create a filtered DataFrame for UI elements that should only show manageable ingredients
        df_estoque_manageable = df_estoque_full[df_estoque_full['Ingrediente'].isin(valid_ingredients)]

        # 4. Create the view for the main stock table (excluding items with zero quantity and non-ingredients)
        if not df_estoque_full.empty and 'Qtd em Estoque' in df_estoque_full.columns:
            df_estoque_view = df_estoque_full[
                df_estoque_full['Ingrediente'].isin(valid_ingredients) & (df_estoque_full['Qtd em Estoque'] != 0)
            ]
        else:
            df_estoque_view = pd.DataFrame(
                columns=["Ingrediente", "Unidade", "Qtd em Estoque", "Preço Médio", "Valor Total"])

        with st.sidebar:
            st.title(f"Olá, {user['name']}")
            menu = st.radio("Menu", ["📊 Visão Geral", "📦 Estoque & Compras", "🍰 Receitas & Produtos", "💸 Vendas",
                                     "🗑️ Desperdícios"])
            st.divider()
            if st.button("Sair"):
                st.session_state.user = None
                st.session_state.view = 'home'
                st.rerun()

        # --- 1. DASHBOARD ---
        if menu == "📊 Visão Geral":
            st.header("Visão Geral do Negócio")

            tab_resumo, tab_analise_vendas, tab_analise_desp = st.tabs(
                ["Resumo", "Análise de Vendas", "Análise de Desperdícios"])

            with tab_resumo:
                if not df_trans.empty:
                    real_trans = df_trans[df_trans['type'].isin(['compra', 'venda_produto', 'ajuste_manual'])]
                    comp = real_trans[real_trans['type'].isin(['compra', 'ajuste_manual'])]['total'].sum()
                    vend = real_trans[real_trans['type'] == 'venda_produto']['total'].sum()

                    desp_df = df_trans[df_trans['type'] == 'desperdicio']
                    total_desp = desp_df['total'].sum() if not desp_df.empty else 0
                    
                    # Filter for ingredients only before checking for negative stock
                    df_ingredients_stock = df_estoque_full[df_estoque_full['Ingrediente'].isin(valid_ingredients)]
                    items_negative = df_ingredients_stock[df_ingredients_stock['Qtd em Estoque'] < 0]

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Compras", f"R$ {comp:.2f}")
                    c2.metric("Vendas", f"R$ {vend:.2f}")
                    c3.metric("Saldo (Caixa)", f"R$ {vend - comp:.2f}")
                    c4.metric("Desperdício", f"R$ {total_desp:.2f}", delta=f"-{total_desp:.2f}", delta_color="inverse")

                    st.subheader("⚠️ Alertas de Estoque")
                    if not items_negative.empty:
                        cost_to_regularize = abs(
                            (items_negative['Qtd em Estoque'] * items_negative['Preço Médio']).sum())
                        st.warning(
                            f"Estoque negativo detectado. Custo estimado para regularizar: R$ {cost_to_regularize:.2f}")
                        st.dataframe(items_negative[['Ingrediente', 'Qtd em Estoque', 'Unidade']], width='stretch')
                    else:
                        st.success("Nenhum item com estoque negativo.")

            with tab_analise_vendas:
                st.subheader("Performance de Vendas")
                sales_df = df_trans[df_trans['type'] == 'venda_produto']
                if not sales_df.empty:
                    sales_grouped = sales_df.groupby('product_name').agg(
                        qtd_vendida=('qty', 'sum'),
                        total_faturado=('total', 'sum'),
                        ocorrencias=('id', 'count')
                    ).reset_index()

                    filter_opt = st.selectbox("Classificar por:",
                                              ["Mais Vendidos (Qtd)", "Maior Faturamento", "Menos Vendidos",
                                               "Menor Faturamento"])

                    if filter_opt == "Mais Vendidos (Qtd)":
                        sales_grouped = sales_grouped.sort_values(by='qtd_vendida', ascending=False)
                    elif filter_opt == "Maior Faturamento":
                        sales_grouped = sales_grouped.sort_values(by='total_faturado', ascending=False)
                    elif filter_opt == "Menos Vendidos":
                        sales_grouped = sales_grouped.sort_values(by='qtd_vendida', ascending=True)
                    else:
                        sales_grouped = sales_grouped.sort_values(by='total_faturado', ascending=True)

                    st.dataframe(sales_grouped, width='stretch')
                else:
                    st.info("Sem vendas.")

            with tab_analise_desp:
                st.subheader("Análise de Perdas")
                desp_df = df_trans[df_trans['type'] == 'desperdicio']
                if not desp_df.empty:
                    c1, c2 = st.columns(2)

                    by_item = desp_df.groupby('waste_item').agg(
                        total_perda=('total', 'sum'),
                        ocorrencias=('id', 'count')
                    ).reset_index().sort_values(by='total_perda', ascending=False)
                    c1.write("**Por Produto (Prejuízo)**")
                    c1.dataframe(by_item, width='stretch')

                    if 'waste_reason' in desp_df.columns:
                        by_reason = desp_df.groupby('waste_reason').agg(
                            total_perda=('total', 'sum'),
                            ocorrencias=('id', 'count')
                        ).reset_index().sort_values(by='ocorrencias', ascending=False)
                        c2.write("**Por Motivo (Frequência)**")
                        c2.dataframe(by_reason, width='stretch')
                else:
                    st.info("Sem desperdícios.")

        # --- 2. ESTOQUE ---
        elif menu == "📦 Estoque & Compras":
            st.header("Estoque Inteligente")
            tab1, tab2, tab3, tab4, tab5 = st.tabs(
                ["📸 Nova Nota (IA)", "➕ Entrada Manual", "📋 Ver Estoque", "🛠️ Gerenciar Estoque", "🛠️ Normalizar"])

            with tab1:
                uploaded_file = st.file_uploader("Nota Fiscal", type=['jpg', 'jpeg'])
                if uploaded_file and st.button("Ler Nota"):
                    with st.spinner("Lendo..."):
                        existing = df_estoque_full['Ingrediente'].unique().tolist()
                        st.session_state.ocr_data = process_receipt_image(uploaded_file, existing)

                if 'ocr_data' in st.session_state and st.session_state.ocr_data:
                    data = st.session_state.ocr_data
                    with st.form("save_stock"):
                        store = st.text_input("Loja", data.get('store'))
                        date = st.date_input("Data", datetime.now())
                        df_items = pd.DataFrame(data['items'])
                        if 'count' not in df_items.columns: df_items['count'] = 1.0
                        if 'unit_size' not in df_items.columns: df_items['unit_size'] = 0.0
                        df_items['calc_total_qty'] = df_items['count'] * df_items['unit_size']

                        edited = st.data_editor(
                            df_items, num_rows="dynamic", width='stretch',
                            column_config={
                                "name": "Produto",
                                "count": st.column_config.NumberColumn("Qtd", min_value=0.1, format="%.1f"),
                                "unit_size": st.column_config.NumberColumn("Tam. Unit", min_value=0.0, format="%.1f"),
                                "unit": st.column_config.SelectboxColumn("Unidade", options=["G", "ML", "UN"],
                                                                         required=True),
                                "calc_total_qty": st.column_config.NumberColumn("Total", disabled=True, format="%.1f"),
                                "total": st.column_config.NumberColumn("Preço (R$)", format="R$ %.2f")
                            },
                            column_order=("name", "count", "unit_size", "unit", "calc_total_qty", "total")
                        )
                        
                        confirmed = st.checkbox("✅ Confirmar dados")
                        
                        if st.form_submit_button("Salvar"):
                            if confirmed:
                                for _, row in edited.iterrows():
                                    final_qty = float(row['count']) if row.get('unit') == 'UN' else float(
                                        row['count']) * float(row['unit_size'])
                                    unit_price = float(row.get('unit_price', 0))
                                    if unit_price == 0 and final_qty > 0: unit_price = float(row['total']) / final_qty
                                    save_transaction({
                                        "type": "compra", "description": row['name'], "qty": final_qty,
                                        "unit_measure": row.get('unit', 'UN'), "unit_price": unit_price,
                                        "total": float(row['total']), "store": store, "date": date.isoformat()
                                    }, user['email'])
                                st.success("Salvo!");
                                st.session_state.ocr_data = None;
                                time.sleep(1);
                                st.rerun()
                            else:
                                st.warning("Por favor, marque a caixa de confirmação para salvar.")

            with tab2:
                st.subheader("Adicionar Item Manualmente")
                with st.form("manual"):
                    sel = st.selectbox("Item", ["➕ NOVO..."] + sorted(df_estoque_manageable['Ingrediente'].unique().tolist()))
                    name = st.text_input("Nome").strip().upper() if sel == "➕ NOVO..." else sel
                    c1, c2, c3, c4 = st.columns(4)
                    cnt = c1.number_input("Qtd", 1.0);
                    sz = c2.number_input("Tam", 0.0)
                    un = c3.selectbox("Unidade", ["G", "ML", "UN"]);
                    pr = c4.number_input("Total R$", 0.0)
                    if st.form_submit_button("Add"):
                        qty = cnt if un == 'UN' else cnt * sz
                        if qty > 0 and pr > 0 and name:
                            save_transaction({
                                "type": "ajuste_manual", "description": name, "qty": qty,
                                "unit_measure": un, "unit_price": pr / qty, "total": pr, "store": "Manual",
                                "date": datetime.now().isoformat()
                            }, user['email'])
                            st.success("Ok");
                            time.sleep(1);
                            st.rerun()

            with tab3:
                if not df_estoque_view.empty:
                    def style_negative(v):
                        return 'color: red;' if isinstance(v, (int, float)) and v < 0 else None

                    st.dataframe(df_estoque_view.style.map(style_negative, subset=['Qtd em Estoque']), width='stretch')
                else:
                    st.info("Estoque vazio.")

            with tab4:
                if not df_estoque_manageable.empty:
                    item = st.selectbox("Item para gerenciar", df_estoque_manageable['Ingrediente'].unique())
                    if item:
                        curr = df_estoque_manageable[df_estoque_manageable['Ingrediente'] == item].iloc[0]
                        st.info(f"""
                        **Dados Atuais:**
                        - Quantidade em Estoque: {curr['Qtd em Estoque']} {curr['Unidade']}
                        - Preço Médio (g/mL/un): R$ {curr['Preço Médio']:.4f}
                        - Valor Total em Estoque: R$ {curr['Valor Total']:.2f}
                        """)
                        act = st.radio("Ação", ["Editar", "Excluir Histórico"])
                        if act == "Editar":
                            with st.form("edit"):
                                nn = st.text_input("Nome", item)
                                current_unit = curr['Unidade']
                                default_index = 0
                                if pd.notna(current_unit) and current_unit in ["G", "ML", "UN"]:
                                    default_index = ["G", "ML", "UN"].index(current_unit)
                                nu = st.selectbox("Unidade", ["G", "ML", "UN"], index=default_index)
                                nq = st.number_input("Nova Qtd", value=float(curr['Qtd em Estoque']));
                                nv = st.number_input("Novo Valor Total", value=float(curr['Valor Total']))
                                if st.form_submit_button("Salvar"):
                                    if nn != item or nu != curr['Unidade']: update_product_name(user['email'], [item],
                                                                                                nn, nu)
                                    if nq != curr['Qtd em Estoque'] or nv != curr['Valor Total']:
                                        save_transaction({"type": "ajuste_manual", "description": nn,
                                                          "qty": nq - curr['Qtd em Estoque'],
                                                          "total": nv - curr['Valor Total'], "unit_measure": nu,
                                                          "store": "Ajuste", "date": datetime.now().isoformat()},
                                                         user['email'])
                                    st.success("Ok");
                                    time.sleep(1);
                                    st.rerun()
                        elif act == "Excluir Histórico" and st.button("Confirmar Exclusão"):
                            delete_stock_items(user['email'], [item]);
                            st.success("Ok");
                            time.sleep(1);
                            st.rerun()
                else:
                    st.info("Nada.")

            with tab5:
                st.subheader("Combinar Itens")
                with st.expander("ℹ️ O que é isso e como usar?", expanded=True):
                    st.markdown("""
                    **O que é a Normalização?**
                    Às vezes, o mesmo produto entra no estoque com nomes ligeiramente diferentes (ex: *"Leite Santa Clara"* e *"Leite Integral 1L"*). 
                    Isso faz com que o sistema ache que são produtos diferentes, atrapalhando o cálculo do seu custo médio e estoque total.
                    
                    **Como usar:**
                    1. Na caixa abaixo, selecione **todos** os itens que são, na verdade, o mesmo produto (ex: selecione as duas variações de leite).
                    2. Em "Nome Padrão", digite como você quer que esse produto seja chamado daqui pra frente (ex: *"LEITE INTEGRAL"*).
                    3. Escolha a unidade padrão (ex: Litros ou Mililitros).
                    4. Clique em **Unificar**.
                    
                    O sistema irá varrer todo o seu histórico e corrigir os nomes antigos para o novo padrão, unificando seu estoque! 🧹✨
                    """)
                if not df_estoque_manageable.empty:
                    its = st.multiselect("Itens", df_estoque_manageable['Ingrediente'].unique())
                    if len(its) > 1:
                        n = st.text_input("Nome Final", its[0]);
                        u = st.selectbox("Unidade Final", ["G", "ML", "UN"])
                        if st.button("Unificar"): update_product_name(user['email'], its, n, u); st.success(
                            "Ok"); time.sleep(1); st.rerun()

        # --- 3. RECEITAS & PRODUTOS ---
        elif menu == "🍰 Receitas & Produtos":
            tab1, tab2 = st.tabs(["➕ Editor de Produto", "📂 Gerenciar Produtos"])

            with tab1:
                header_text = "Editar Produto" if st.session_state.editing_recipe_id else "Novo Produto"
                st.header(header_text)

                if df_estoque_manageable.empty:
                    st.warning("Adicione itens ao estoque primeiro.")
                else:
                    col_esq, col_dir = st.columns([1, 1.2])
                    with col_esq:
                        st.subheader("1. Ingredientes")
                        ingrediente = st.selectbox("Item", df_estoque_manageable['Ingrediente'].unique())
                        if ingrediente:
                            dados_est = df_estoque_manageable[df_estoque_manageable['Ingrediente'] == ingrediente].iloc[0]
                            unidade_db = dados_est['Unidade']
                            c1, c2 = st.columns(2)
                            qtd_input = c1.number_input("Qtd", min_value=0.0, step=0.1, key="qtd_ing")
                            opcoes_unidade = ['G', 'KG'] if unidade_db == 'G' else ['ML', 'L', 'Xícara (240ml)',
                                                                                    'Colher (15ml)'] if unidade_db == 'ML' else [
                                'UN']
                            unidade_input = c2.selectbox("Unidade", opcoes_unidade, key="unit_ing")
                            if st.button("Adicionar Ingrediente"):
                                if qtd_input > 0:
                                    qtd_real = qtd_input
                                    if unidade_input in ['KG', 'L']:
                                        qtd_real = qtd_input * 1000
                                    elif 'Xícara' in unidade_input:
                                        qtd_real = qtd_input * 240
                                    elif 'Colher' in unidade_input:
                                        qtd_real = qtd_input * 15
                                    cost = qtd_real * dados_est['Preço Médio']
                                    st.session_state.recipe_items.append({
                                        "type": "stock_item", "name": ingrediente, "qtd_display": qtd_input,
                                        "unit_display": unidade_input, "qtd_real": qtd_real, "unit_db": unidade_db,
                                        "cost": cost
                                    });
                                    st.rerun()
                        st.markdown("---");
                        st.subheader("2. Custos Extras")
                        extra_name = st.text_input("Descrição", key="extra_name")
                        extra_val = st.number_input("Custo (R$)", min_value=0.0, step=0.1, key="extra_val")
                        if st.button("Adicionar Custo Extra"):
                            if extra_name and extra_val > 0:
                                st.session_state.extra_costs.append({"name": extra_name, "cost": extra_val});
                                st.rerun()

                    with col_dir:
                        st.subheader("Resumo")
                        st.session_state.product_name = st.text_input("Nome do Produto Final",
                                                                      value=st.session_state.product_name,
                                                                      placeholder="Ex: Bolo de Cenoura")

                        total_cost = 0
                        if st.session_state.recipe_items:
                            st.markdown("##### Ingredientes")
                            for i, item in enumerate(st.session_state.recipe_items):
                                col_text, col_btn = st.columns([4, 1])
                                cost_val = item.get('cost', 0);
                                total_cost += cost_val
                                col_text.write(
                                    f"• {item['qtd_display']} {item['unit_display']} {item['name']} (**R$ {cost_val:.2f}**)")
                                if col_btn.button("❌", key=f"del_ing_{i}"): st.session_state.recipe_items.pop(
                                    i); st.rerun()
                        if st.session_state.extra_costs:
                            st.markdown("##### Extras")
                            for i, extra in enumerate(st.session_state.extra_costs):
                                col_text, col_btn = st.columns([4, 1])
                                total_cost += extra['cost']
                                col_text.write(f"• {extra['name']} (**R$ {extra['cost']:.2f}**)")
                                if col_btn.button("❌", key=f"del_ext_{i}"): st.session_state.extra_costs.pop(
                                    i); st.rerun()

                        st.divider();
                        st.markdown(f"#### 💰 Custo Total: R$ {total_cost:.2f}")

                        st.markdown("### Precificação")

                        def update_prices():
                            current_cost = sum(i['cost'] for i in st.session_state.recipe_items) + sum(
                                e['cost'] for e in st.session_state.extra_costs)
                            new_profit = st.session_state.widget_profit
                            if current_cost > 0:
                                st.session_state.target_profit = new_profit
                                st.session_state.target_price = current_cost * (1 + (new_profit / 100))
                                st.session_state.widget_price = st.session_state.target_price

                        def update_margins():
                            current_cost = sum(i['cost'] for i in st.session_state.recipe_items) + sum(
                                e['cost'] for e in st.session_state.extra_costs)
                            new_price = st.session_state.widget_price
                            if current_cost > 0 and new_price > 0:
                                st.session_state.target_price = new_price
                                st.session_state.target_profit = ((new_price - current_cost) / current_cost) * 100
                                st.session_state.widget_profit = st.session_state.target_profit

                        if st.session_state.target_price == 0 and total_cost > 0 and not st.session_state.editing_recipe_id:
                            st.session_state.target_price = total_cost * 2;
                            st.session_state.target_profit = 100.0
                            st.session_state.widget_price = st.session_state.target_price
                            st.session_state.widget_profit = st.session_state.target_profit

                        c1, c2 = st.columns(2)
                        c1.number_input("Margem (%)", min_value=0.0, step=5.0,
                                        value=float(st.session_state.target_profit), key="widget_profit",
                                        on_change=update_prices)
                        c2.number_input("Preço Final (R$)", min_value=0.0, step=1.0,
                                        value=float(st.session_state.target_price), key="widget_price",
                                        on_change=update_margins)

                        profit_value = st.session_state.target_price - total_cost
                        st.success(f"💵 Lucro Líquido por unidade: **R$ {profit_value:.2f}**")

                        cols_save = st.columns([1, 1])
                        if cols_save[0].button("💾 Salvar Produto", type="primary"):
                            if st.session_state.product_name:
                                recipe_data = {
                                    "type": "receita_produto", "description": st.session_state.product_name,
                                    "ingredients": st.session_state.recipe_items,
                                    "extras": st.session_state.extra_costs,
                                    "total_cost": total_cost, "profit_margin": st.session_state.target_profit,
                                    "sale_price": st.session_state.target_price
                                }
                                if st.session_state.editing_recipe_id: recipe_data[
                                    'id'] = st.session_state.editing_recipe_id
                                save_transaction(recipe_data, user['email'])
                                st.success("Salvo!");
                                time.sleep(1)
                                st.session_state.recipe_items = [];
                                st.session_state.extra_costs = [];
                                st.session_state.target_profit = 100.0;
                                st.session_state.target_price = 0.0;
                                st.session_state.product_name = "";
                                st.session_state.editing_recipe_id = None;
                                st.rerun()
                            else:
                                st.error("Nome obrigatório.")
                        if cols_save[1].button("Limpar"):
                            st.session_state.recipe_items = [];
                            st.session_state.extra_costs = [];
                            st.session_state.target_profit = 100.0;
                            st.session_state.target_price = 0.0;
                            st.session_state.product_name = "";
                            st.session_state.editing_recipe_id = None;
                            st.rerun()

            with tab2:
                st.header("Seus Produtos")
                if not df_trans.empty:
                    recipes = df_trans[df_trans['type'] == 'receita_produto'].copy()
                    if not recipes.empty:
                        for _, recipe in recipes.iterrows():
                            with st.expander(
                                    f"🧾 {recipe['description']} (Venda: R$ {recipe.get('sale_price', 0):.2f})"):
                                c1, c2, c3 = st.columns(3)
                                c1.metric("Custo Base", f"R$ {recipe.get('total_cost', 0):.2f}")
                                c2.metric("Margem", f"{recipe.get('profit_margin', 0):.0f}%")
                                c3.metric("Lucro",
                                          f"R$ {(recipe.get('sale_price', 0) - recipe.get('total_cost', 0)):.2f}")
                                col_a, col_b = st.columns([1, 1])
                                if col_a.button("✏️ Editar Completo", key=f"load_{recipe['id']}",
                                                on_click=load_recipe_to_edit, args=(recipe,)):
                                    st.success("Carregado! Volte a aba Editor de Produto");
                                    time.sleep(0.5)
                                if col_b.button("🗑️ Excluir", key=f"del_r_{recipe['id']}"):
                                    if delete_transaction(recipe['id'], user['email']): st.success(
                                        "Excluído."); time.sleep(0.5); st.rerun()
                    else:
                        st.info("Nenhum produto cadastrado.")
                else:
                    st.info("Sem dados.")

        # --- 4. VENDAS ---
        elif menu == "💸 Vendas":
            st.header("Vendas")
            tab_registrar, tab_gerenciar = st.tabs(["➕ Registrar Venda", "📂 Gerenciar Vendas"])

            with tab_registrar:
                st.subheader("Registrar Venda de Produto")
                recipes = []
                if not df_trans.empty:
                    recipes_df = df_trans[df_trans['type'] == 'receita_produto']
                    if not recipes_df.empty: recipes = recipes_df.to_dict('records')

                if not recipes:
                    st.warning("Cadastre produtos antes de registrar uma venda.")
                else:
                    recipe_options = {r['description']: r for r in recipes}
                    sel_prod = st.selectbox("Produto Vendido", list(recipe_options.keys()))
                    if sel_prod:
                        prod = recipe_options[sel_prod]
                        missing = []
                        if 'ingredients' in prod:
                            for ing in prod['ingredients']:
                                stock = df_estoque_full[df_estoque_full['Ingrediente'] == ing['name']]
                                curr = stock['Qtd em Estoque'].values[0] if not stock.empty else 0
                                if curr <= 0: missing.append(f"{ing['name']} ({curr:.2f})")

                        if missing: st.warning(f"Atenção, estoque baixo ou negativo para: {', '.join(missing)}")

                        with st.form("venda_f"):
                            c1, c2 = st.columns(2)
                            qtd_v = c1.number_input("Quantidade Vendida", 1.0, step=1.0)
                            price_v = c2.number_input("Preço Unitário de Venda (R$)", value=float(prod.get('sale_price', 0)))
                            total_v = qtd_v * price_v
                            st.metric("Valor Total da Venda", f"R$ {total_v:.2f}")

                            st.markdown("---")
                            st.subheader("Informações do Cliente (Opcional)")
                            client = st.text_input("Nome do Cliente")
                            phone = st.text_input("Telefone")
                            addr = st.text_input("Endereço de Entrega")
                            ch = st.selectbox("Canal de Venda", ["Pessoalmente", "WhatsApp", "Instagram", "Outro"])
                            
                            conf_stock = st.checkbox("Confirmar venda mesmo com estoque baixo/negativo") if missing else True

                            if st.form_submit_button("✅ Confirmar Venda"):
                                if not conf_stock:
                                    st.error("Confirme a ciência do estoque baixo/negativo para prosseguir.")
                                else:
                                    sale = {
                                        "type": "venda_produto", "description": f"VENDA: {prod['description']}",
                                        "product_id": prod['id'], "product_name": prod['description'],
                                        "qty": qtd_v, "unit_price": price_v, "total": total_v,
                                        "date": datetime.now().isoformat(), "client_name": client,
                                        "client_phone": phone, "client_address": addr, "sales_channel": ch
                                    }
                                    save_transaction(sale, user['email'])
                                    
                                    # Deduct ingredients from stock
                                    if 'ingredients' in prod:
                                        for ing in prod['ingredients']:
                                            used = float(ing['qtd_real']) * qtd_v
                                            stock = df_estoque_full[df_estoque_full['Ingrediente'] == ing['name']]
                                            curr = stock['Qtd em Estoque'].values[0] if not stock.empty else 0
                                            t_type = "uso_receita_negativo" if curr <= 0 else "uso_receita"
                                            save_transaction({
                                                "type": t_type, "description": ing['name'], "qty": used,
                                                "unit_measure": ing.get('unit_db', 'UN'), "total": 0,
                                                "related_sale_id": sale['id'], "date": datetime.now().isoformat()
                                            }, user['email'])
                                    st.success("Venda registrada com sucesso!");
                                    time.sleep(1);
                                    st.rerun()
            
            with tab_gerenciar:
                st.subheader("Histórico de Vendas")
                sales_df = df_trans[df_trans['type'] == 'venda_produto'].copy()
                if sales_df.empty:
                    st.info("Nenhuma venda registrada ainda.")
                else:
                    sales_df['date'] = pd.to_datetime(sales_df['date']).dt.strftime('%d/%m/%Y %H:%M')
                    sales_df = sales_df.sort_values(by='date', ascending=False)

                    for _, sale in sales_df.iterrows():
                        with st.expander(f"Venda de **{sale['product_name']}** em {sale['date']} - Total: R$ {sale['total']:.2f}"):
                            st.markdown(f"""
                            - **Produto:** {sale['product_name']}
                            - **Quantidade:** {sale['qty']}
                            - **Preço Unitário:** R$ {sale.get('unit_price', 0):.2f}
                            - **Cliente:** {sale.get('client_name', 'Não informado')}
                            - **Canal:** {sale.get('sales_channel', 'Não informado')}
                            """)
                            
                            if st.button("🗑️ Excluir Venda", key=f"del_sale_{sale['id']}", help="Atenção: Isso irá reverter a baixa de estoque dos ingredientes."):
                                # Find and delete related ingredient usage transactions
                                if 'related_sale_id' in df_trans.columns:
                                    related_trans_ids = df_trans[df_trans['related_sale_id'] == sale['id']]['id'].tolist()
                                    for trans_id in related_trans_ids:
                                        delete_transaction(trans_id, user['email'])
                                
                                # Delete the sale transaction itself
                                if delete_transaction(sale['id'], user['email']):
                                    st.success("Venda e movimentações de estoque associadas foram excluídas.")
                                    time.sleep(1.5)
                                    st.rerun()

        # --- 5. DESPERDÍCIOS ---
        elif menu == "🗑️ Desperdícios":
            st.header("Registro de Desperdícios")
            wtype = st.radio("Tipo", ["Item Estoque", "Produto Final"])
            with st.form("waste"):
                c1, c2 = st.columns(2)
                if wtype == "Item Estoque":
                    if not df_estoque_manageable.empty:
                        isel = c1.selectbox("Item", df_estoque_manageable['Ingrediente'].unique())
                        if isel:
                            data = df_estoque_manageable[df_estoque_manageable['Ingrediente'] == isel].iloc[0]
                            qw = c1.number_input("Qtd Perdida", 0.0)
                            wn, wc, wr = isel, qw * data['Preço Médio'], 0
                    else:
                        st.warning("Estoque vazio.")
                else:
                    recs = df_trans[df_trans['type'] == 'receita_produto'] if not df_trans.empty else pd.DataFrame()
                    if not recs.empty:
                        recipe_opts = {r['description']: r for r in recs.to_dict('records')}
                        psel = c1.selectbox("Produto", list(recipe_opts.keys()))
                        if psel:
                            prod = recipe_opts[psel]
                            qp = c1.number_input("Qtd", 1.0)
                            wn, wc, wr = psel, prod['total_cost'] * qp, prod['sale_price'] * qp
                    else:
                        st.warning("Sem produtos.")

                reas = c2.selectbox("Motivo", LISTA_MOTIVOS)
                if st.form_submit_button("Registrar"):
                    rec = {"type": "desperdicio", "description": f"Desp: {wn}", "waste_item": wn, "waste_reason": reas,
                           "qty": 1 if wtype == "Produto Final" else qw, "total": wc, "lost_revenue": wr,
                           "date": datetime.now().isoformat()}
                    save_transaction(rec, user['email'])
                    if wtype == "Produto Final" and 'ingredients' in prod:
                        for ing in prod['ingredients']:
                            used = float(ing['qtd_real']) * qp
                            save_transaction({"type": "desperdicio", "description": ing['name'], "qty": used,
                                              "unit_measure": ing.get('unit_db', 'UN'), "total": 0,
                                              "related_waste_id": rec['id'], "date": datetime.now().isoformat()},
                                             user['email'])
                    st.error(f"Prejuízo: R$ {wc:.2f}");
                    time.sleep(1.5);
                    st.rerun()


if __name__ == "__main__":
    main()
